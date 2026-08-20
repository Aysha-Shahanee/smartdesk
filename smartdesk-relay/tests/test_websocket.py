import pytest
from starlette.websockets import WebSocketDisconnect


def register(client, token, installation_id):
    socket = client.websocket_connect("/ws")
    socket.__enter__()
    socket.send_json({"type": "register", "installation_id": installation_id, "token": token(installation_id)})
    assert socket.receive_json() == {"type": "registered", "installation_id": installation_id}
    return socket


def test_valid_registration_and_disconnect_cleanup(client, app, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "register", "installation_id": 123, "token": token(123)})
        assert socket.receive_json()["type"] == "registered"
        assert client.portal.call(app.state.connections.connection_count, 123) == 1
    assert client.portal.call(app.state.connections.connection_count, 123) == 0


def test_invalid_auth_and_impersonation_are_rejected(client, token):
    for installation_id, credential in [(123, "invalid"), (456, token(123))]:
        with client.websocket_connect("/ws") as socket:
            socket.send_json({"type": "register", "installation_id": installation_id, "token": credential})
            with pytest.raises(WebSocketDisconnect) as closed:
                socket.receive_json()
            assert closed.value.code == 1008


def test_matching_client_receives_only_minimal_event(client, signed_post, event, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "register", "installation_id": 123, "token": token(123)})
        socket.receive_json()
        assert signed_post(event(123)).json()["forwarded"] == 1
        assert socket.receive_json() == {
            "type": "github_project_item_changed",
            "installation_id": 123,
            "project_item_node_id": "PVTI_1",
            "project_node_id": "PVT_1",
            "content_node_id": "I_1",
            "action": "edited",
        }


def test_other_installation_is_not_forwarded(client, signed_post, event, token):
    with client.websocket_connect("/ws") as socket:
        socket.send_json({"type": "register", "installation_id": 123, "token": token(123)})
        socket.receive_json()
        assert signed_post(event(456)).json()["forwarded"] == 0


def test_multiple_clients_for_installation_all_receive(client, signed_post, event, token):
    with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
        for socket in (first, second):
            socket.send_json({"type": "register", "installation_id": 123, "token": token(123)})
            socket.receive_json()
        assert signed_post(event()).json()["forwarded"] == 2
        assert first.receive_json()["project_item_node_id"] == "PVTI_1"
        assert second.receive_json()["project_item_node_id"] == "PVTI_1"


def test_send_failure_is_removed_without_crashing(client, app):
    class BrokenSocket:
        async def send_json(self, message):
            raise RuntimeError("gone")

    broken = BrokenSocket()
    client.portal.call(app.state.connections.register, 123, broken)
    assert client.portal.call(app.state.connections.send, 123, {"safe": True}) == 0
    assert client.portal.call(app.state.connections.connection_count, 123) == 0
