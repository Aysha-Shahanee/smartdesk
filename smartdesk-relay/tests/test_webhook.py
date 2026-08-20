import hashlib
import hmac


def test_health_exposes_no_configuration(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_valid_webhook_without_client_is_accepted(signed_post, event):
    response = signed_post(event())
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "forwarded": 0}


def test_invalid_and_missing_signature_are_rejected(client):
    assert client.post("/github/webhook", content=b"{}").status_code == 401
    assert client.post(
        "/github/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}
    ).status_code == 401


def test_malformed_json_is_rejected_after_signature_check(client):
    body = b"not-json"
    digest = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    response = client.post(
        "/github/webhook", content=body, headers={"X-Hub-Signature-256": f"sha256={digest}"}
    )
    assert response.status_code == 400


def test_unsupported_event_is_safe(signed_post):
    response = signed_post({"anything": "ignored"}, event="issues")
    assert response.status_code == 200
    assert response.json()["reason"] == "unsupported_event"


def test_missing_installation_is_rejected_safely(signed_post, event):
    payload = event()
    payload.pop("installation")
    assert signed_post(payload).status_code == 422


def test_oversized_payload_is_rejected(client):
    assert client.post(
        "/github/webhook", content=b"x", headers={"Content-Length": "1048577"}
    ).status_code == 413

