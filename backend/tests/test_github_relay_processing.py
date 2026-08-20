import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.db.github import GitHubInitialPredictionRecord
from app.services.github_integration_service import GitHubIntegrationService
from app.services.github_prediction_service import GitHubPredictionService
from app.services.relay_client import RelayClientService, RelayNotification
from github_data_collection.database import Base as CollectorBase, CollectedTask
from github_data_collection.repositories import CollectedTaskRepository
from github_data_collection.task_metadata_service import TaskMetadataService
from github_data_collection.webhook_handler import handle_github_webhook_event


class FakePredictor:
    def __init__(self):
        self.calls = 0

    def predict(self, metadata):
        self.calls += 1
        return {
            "low_hours": 1.0,
            "typical_hours": 4.0,
            "high_hours": 12.0,
            "model_version": "relay-test-v1",
        }


class FakeActive:
    def __init__(self):
        self.rows = set()

    def add(self, metadata):
        self.rows.add(metadata["project_item_id"])

    def remove(self, item_id):
        self.rows.discard(item_id)


class FakeStates:
    def __init__(self):
        self.rows = {}

    def get(self, item_id):
        return self.rows.get(item_id)

    def upsert(self, item_id, project_id, name, logical):
        self.rows[item_id] = {
            "project_id": project_id,
            "status_option_name": name,
            "logical_status": logical,
        }


class FakeDeliveries:
    def is_processed(self, _delivery_id):
        return False

    def mark_processed(self, _delivery_id):
        pass


class FakeConnectionRepository:
    def __init__(self):
        self.connection = SimpleNamespace(
            user_id="local_user",
            connection_status="connected",
            installation_id=123,
            selected_project_id="PVT_1",
            github_login="octocat",
        )

    def get_connection(self, user_id):
        return self.connection if user_id == "local_user" else None

    def get_connection_by_project(self, project_id):
        return self.connection if project_id == self.connection.selected_project_id else None


class RelayProcessingHarness:
    def __init__(self):
        engine_options = {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        }
        smart_engine = create_engine("sqlite:///:memory:", **engine_options)
        Base.metadata.create_all(
            smart_engine, tables=[GitHubInitialPredictionRecord.__table__]
        )
        self.smart_session = sessionmaker(bind=smart_engine)()
        collector_engine = create_engine("sqlite:///:memory:", **engine_options)
        CollectorBase.metadata.create_all(collector_engine)
        collector_sessions = sessionmaker(bind=collector_engine, expire_on_commit=False)
        self.collected = CollectedTaskRepository(session_factory=collector_sessions)
        self.active = FakeActive()
        self.states = FakeStates()
        self.deliveries = FakeDeliveries()
        self.predictor = FakePredictor()
        self.status = "Doing"
        self.assignees = ["octocat"]
        prediction = GitHubPredictionService(self.smart_session, self.predictor)
        self.metadata_service = TaskMetadataService(
            collected=self.collected,
            active=self.active,
            connected_github_login="octocat",
            fetcher=self.fetch_metadata,
            on_lifecycle_started=prediction.predict_initial,
        )
        self.service = GitHubIntegrationService(self.smart_session)
        self.service.repository = FakeConnectionRepository()
        self.service._token = lambda _user_id: "installation-token"
        self.service._metadata_service = lambda *_args: self.metadata_service

    def fetch_metadata(self, item_id, token=None):
        assert token == "installation-token"
        return {
            "project_item_id": item_id,
            "project_id": "PVT_1",
            "issue_id": f"I_{item_id}",
            "issue_number": 42,
            "title": "Authoritative title from GitHub",
            "description": "Authoritative body from GitHub",
            "labels": ["bug"],
            "assignees": list(self.assignees),
            "repository": "owner/repository",
            "smartdesk_user_id": "local_user",
            "detected_start_time": "2026-08-20T10:00:00Z",
        }

    @staticmethod
    def mapping(_project_id, name):
        return {
            "Todo": "NOT_STARTED",
            "Doing": "ACTIVE",
            "Done": "DONE",
        }.get(name, "OTHER")

    def dispatch(self, item_id="PVTI_1", project_id="PVT_1"):
        def shared_handler(payload, headers, token=None, metadata_service=None):
            return handle_github_webhook_event(
                payload,
                headers,
                token=token,
                metadata_service=metadata_service,
                state_repository=self.states,
                delivery_repository=self.deliveries,
                status_mapper=self.mapping,
                status_fetcher=lambda _item, supplied_token: (
                    self.status if supplied_token == "installation-token" else None
                ),
            )

        with patch(
            "app.services.github_integration_service.handle_github_webhook_event",
            side_effect=shared_handler,
        ):
            return self.service.process_relay_notification(
                installation_id=123,
                project_item_node_id=item_id,
                project_node_id=project_id,
                content_node_id="I_1",
                action="edited",
            )

    def predictions(self):
        return self.smart_session.query(GitHubInitialPredictionRecord).all()

    def lifecycles(self):
        with self.collected.session_factory() as session:
            return session.query(CollectedTask).order_by(CollectedTask.id).all()


def test_relay_active_uses_existing_lifecycle_prediction_and_is_idempotent():
    harness = RelayProcessingHarness()
    harness.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
    assert harness.dispatch()
    assert harness.dispatch()
    assert len(harness.lifecycles()) == 1
    assert len(harness.predictions()) == 1
    assert harness.predictor.calls == 1
    prediction = harness.predictions()[0]
    assert prediction.predicted_low_hours == 1.0
    assert prediction.predicted_typical_hours == 4.0
    assert prediction.predicted_high_hours == 12.0
    assert prediction.model_version == "relay-test-v1"


def test_relay_ownership_filter_uses_connected_human_login():
    for assignees, tracked in (
        (["octocat"], True),
        (["teammate", "OCTOCAT"], True),
        (["teammate"], False),
        ([], False),
    ):
        harness = RelayProcessingHarness()
        harness.assignees = assignees
        harness.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        assert harness.dispatch()
        assert bool(harness.lifecycles()) is tracked
        assert bool(harness.predictions()) is tracked


def test_relay_not_started_active_done_and_done_active_reopen():
    harness = RelayProcessingHarness()
    harness.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
    harness.status = "Doing"
    harness.dispatch()
    assert "PVTI_1" in harness.active.rows
    harness.status = "Done"
    harness.dispatch()
    first = harness.lifecycles()[0]
    assert first.completed_at is not None
    assert "PVTI_1" not in harness.active.rows
    harness.status = "Doing"
    harness.dispatch()
    assert len(harness.lifecycles()) == 2
    assert len(harness.predictions()) == 2
    assert "PVTI_1" in harness.active.rows


def test_unknown_project_and_wrong_installation_are_ignored_before_fetch():
    harness = RelayProcessingHarness()
    harness.metadata_service.fetcher = Mock(side_effect=AssertionError("must not fetch"))
    assert not harness.dispatch(project_id="PVT_unknown")
    assert not harness.service.process_relay_notification(
        installation_id=999,
        project_item_node_id="PVTI_1",
        project_node_id="PVT_1",
        content_node_id="I_1",
        action="edited",
    )
    harness.metadata_service.fetcher.assert_not_called()


def test_temporary_authoritative_status_failure_does_not_change_state():
    harness = RelayProcessingHarness()
    harness.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
    before = dict(harness.states.get("PVTI_1"))

    def shared_handler(payload, headers, token=None, metadata_service=None):
        return handle_github_webhook_event(
            payload,
            headers,
            token=token,
            metadata_service=metadata_service,
            state_repository=harness.states,
            delivery_repository=harness.deliveries,
            status_mapper=harness.mapping,
            status_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("temporary")),
        )

    with patch(
        "app.services.github_integration_service.handle_github_webhook_event",
        side_effect=shared_handler,
    ):
        try:
            harness.service.process_relay_notification(
                installation_id=123,
                project_item_node_id="PVTI_1",
                project_node_id="PVT_1",
                content_node_id="I_1",
                action="edited",
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("temporary failure should propagate to the safe relay boundary")
    assert harness.states.get("PVTI_1") == before
    assert harness.lifecycles() == []
    assert harness.predictions() == []


def test_direct_and_relay_paths_call_the_same_core_processor():
    harness = RelayProcessingHarness()
    calls = []

    def record(payload, headers, **kwargs):
        calls.append((payload, headers, kwargs))

    direct_payload = {
        "projects_v2_item": {"node_id": "PVTI_direct", "project_node_id": "PVT_1"}
    }
    with patch(
        "app.services.github_integration_service.handle_github_webhook_event",
        side_effect=record,
    ):
        harness.service.process_webhook(
            direct_payload, {"X-GitHub-Event": "projects_v2_item"}
        )
        assert harness.service.process_relay_notification(
            installation_id=123,
            project_item_node_id="PVTI_relay",
            project_node_id="PVT_1",
            content_node_id="I_1",
            action="edited",
        )
    assert len(calls) == 2
    assert all(call[1]["X-GitHub-Event"] == "projects_v2_item" for call in calls)
    assert all(call[2]["token"] == "installation-token" for call in calls)
    assert calls[0][2]["metadata_service"] is harness.metadata_service
    assert calls[1][2]["metadata_service"] is harness.metadata_service


def test_direct_then_relay_overlap_remains_idempotent():
    harness = RelayProcessingHarness()
    harness.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")

    def shared_handler(payload, headers, token=None, metadata_service=None):
        return handle_github_webhook_event(
            payload,
            headers,
            token=token,
            metadata_service=metadata_service,
            state_repository=harness.states,
            delivery_repository=harness.deliveries,
            status_mapper=harness.mapping,
            status_fetcher=lambda *_: "Doing",
        )

    with patch(
        "app.services.github_integration_service.handle_github_webhook_event",
        side_effect=shared_handler,
    ):
        harness.service.process_webhook(
            {"projects_v2_item": {
                "node_id": "PVTI_1", "project_node_id": "PVT_1"
            }},
            {"X-GitHub-Event": "projects_v2_item", "X-GitHub-Delivery": "direct-1"},
        )
        assert harness.service.process_relay_notification(
            installation_id=123,
            project_item_node_id="PVTI_1",
            project_node_id="PVT_1",
            content_node_id="I_1",
            action="edited",
        )
    assert len(harness.lifecycles()) == 1
    assert len(harness.predictions()) == 1
    assert harness.predictor.calls == 1


def test_malformed_relay_identifier_never_reaches_processing_handler():
    called = False

    def handler(_notification):
        nonlocal called
        called = True

    service = RelayClientService(Mock(), notification_handler=handler)
    assert service.handle_message(json.dumps({
        "type": "github_project_item_changed",
        "installation_id": 123,
        "project_item_node_id": "not-a-node-id",
        "project_node_id": "PVT_1",
        "content_node_id": "I_1",
        "action": "edited",
    }), 123) is None
    assert not called


def test_relay_client_dispatches_valid_notification_to_processing_handler():
    async def exercise():
        handled = []

        class Socket:
            def __init__(self):
                self.messages = [json.dumps({
                    "type": "github_project_item_changed",
                    "installation_id": 123,
                    "project_item_node_id": "PVTI_1",
                    "project_node_id": "PVT_1",
                    "content_node_id": "I_1",
                    "action": "edited",
                })]

            async def send(self, _message):
                pass

            async def recv(self):
                return json.dumps({"type": "registered", "installation_id": 123})

            def __aiter__(self):
                return self

            async def __anext__(self):
                if not self.messages:
                    raise StopAsyncIteration
                return self.messages.pop()

        class Connection:
            async def __aenter__(self):
                return Socket()

            async def __aexit__(self, *_args):
                pass

        settings = Mock(
            SMARTDESK_RELAY_URL="ws://relay/ws",
            SMARTDESK_RELAY_CONNECT_TIMEOUT_SECONDS=1,
            SMARTDESK_RELAY_CLIENT_AUTH_SECRET="secret",
        )
        service = RelayClientService(
            settings,
            connector=lambda *_args, **_kwargs: Connection(),
            notification_handler=handled.append,
        )
        assert await service._connect_and_listen(123)
        assert len(handled) == 1
        assert handled[0].project_item_node_id == "PVTI_1"

    asyncio.run(exercise())
