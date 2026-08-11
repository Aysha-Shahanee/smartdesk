import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from github_data_collection.config import MODULE_DIR, Settings
from github_data_collection.database import Base, CollectedTask
from github_data_collection.collectors.status_monitor import fetch_all_project_items
from github_data_collection.collectors.metadata_collector import UnsupportedProjectItemError
from github_data_collection.initial_sync import initial_sync
from github_data_collection.project_service import discover_projects
from github_data_collection.repositories import CollectedTaskRepository
from github_data_collection.task_metadata_service import TaskMetadataService
from github_data_collection.webhook_handler import handle_github_webhook_event


class ConfigurationTests(unittest.TestCase):
    def test_env_file_is_anchored_to_module(self):
        self.assertEqual(Path(Settings.model_config["env_file"]), MODULE_DIR / ".env")

    def test_missing_credentials_are_allowed_until_live_access(self):
        configured = Settings(
            _env_file=None,
            GITHUB_TOKEN="",
            GITHUB_OWNER="",
            PROJECT_NUMBER=1,
            POLL_INTERVAL_SECONDS=1,
        )
        with self.assertRaisesRegex(RuntimeError, "GITHUB_TOKEN, GITHUB_OWNER"):
            configured.validate_github_access()


class LifecycleTimestampTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.repository = CollectedTaskRepository(session_factory=self.sessions)

    @staticmethod
    def metadata(started_at):
        return {
            "project_item_id": "PVTI_1",
            "issue_id": "I_1",
            "title": "Task",
            "detected_start_time": started_at,
        }

    def rows(self):
        with self.sessions() as session:
            return session.query(CollectedTask).order_by(CollectedTask.id).all()

    def test_completion_preserves_started_at_and_sets_completed_at(self):
        self.repository.insert(self.metadata("2026-01-01T10:00:00Z"))
        self.repository.complete_open(
            "PVTI_1", self.metadata("2026-01-01T11:00:00Z"),
            completed_at="2026-01-01T12:00:00Z",
        )

        row = self.rows()[0]
        self.assertEqual(row.started_at, "2026-01-01T10:00:00Z")
        self.assertEqual(row.detected_start_time, "2026-01-01T10:00:00Z")
        self.assertEqual(row.completed_at, "2026-01-01T12:00:00Z")

    def test_reopened_task_creates_a_new_lifecycle(self):
        self.repository.insert(self.metadata("2026-01-01T10:00:00Z"))
        self.repository.complete_open(
            "PVTI_1", self.metadata("2026-01-01T11:00:00Z"),
            completed_at="2026-01-01T12:00:00Z",
        )
        self.repository.insert(self.metadata("2026-01-02T09:00:00Z"))

        first, reopened = self.rows()
        self.assertEqual(first.completed_at, "2026-01-01T12:00:00Z")
        self.assertEqual(reopened.started_at, "2026-01-02T09:00:00Z")
        self.assertIsNone(reopened.completed_at)

    def test_update_open_resolves_duplicate_open_lifecycles_without_deleting_history(self):
        self.repository.insert(self.metadata("2026-01-01T10:00:00Z"))
        self.repository.insert(self.metadata("2026-01-01T11:00:00Z"))

        lifecycle_id = self.repository.update_open(
            "PVTI_1", self.metadata("2026-01-01T11:00:00Z")
        )

        first, latest = self.rows()
        self.assertEqual(lifecycle_id, latest.id)
        self.assertIsNotNone(first.completed_at)
        self.assertIsNone(latest.completed_at)


class FakeStates:
    def __init__(self):
        self.rows = {}

    def get(self, item_id):
        return self.rows.get(item_id)

    def upsert(self, item_id, project_id, name, logical):
        self.rows[item_id] = {
            "project_item_id": item_id, "project_id": project_id,
            "status_option_name": name, "logical_status": logical,
        }


class FakeDeliveries:
    def __init__(self):
        self.ids = set()

    def is_processed(self, delivery_id):
        return delivery_id in self.ids if delivery_id else False

    def mark_processed(self, delivery_id):
        if delivery_id:
            self.ids.add(delivery_id)


class FakeActive:
    def __init__(self):
        self.removed = []

    def remove(self, item_id):
        self.removed.append(item_id)


class FakeMetadata:
    def __init__(self):
        self.started = []
        self.completed = []
        self.synced = []
        self.inactive = []
        self.active = FakeActive()

    def task_started(self, item_id, token=None):
        self.started.append(item_id)

    def task_completed(self, item_id, token=None):
        self.completed.append(item_id)

    def synchronize_active(self, item_id, is_new=None, token=None):
        self.synced.append((item_id, is_new))

    def synchronize_inactive(self, item_id, token=None):
        self.inactive.append(item_id)


def mapper(mapping):
    return lambda project_id, name: mapping.get(name, "OTHER")


def event(project="PVT_1", item="PVTI_1", old="Todo", new="In Progress"):
    return {
        "projects_v2_item": {
            "node_id": item,
            "project_node_id": project,
            "status_option_name": new,
        },
        "changes": {"field_value": {"from": {"name": old}, "to": {"name": new}}},
    }


class WebhookTests(unittest.TestCase):
    def test_two_mappings_and_any_transition_into_active(self):
        for mapping, old, active in (
            ({"Todo": "NOT_STARTED", "In Progress": "ACTIVE", "Done": "DONE"}, "Todo", "In Progress"),
            ({"Backlog": "NOT_STARTED", "Development": "ACTIVE", "Released": "DONE"}, "Backlog", "Development"),
        ):
            service, states = FakeMetadata(), FakeStates()
            handle_github_webhook_event(
                event(old=old, new=active), {"X-GitHub-Event": "projects_v2_item"}, metadata_service=service,
                state_repository=states, delivery_repository=FakeDeliveries(),
                status_mapper=mapper(mapping),
            )
            self.assertEqual(service.started, ["PVTI_1"])

    def test_active_done_and_done_reopened(self):
        mapping = {"Development": "ACTIVE", "Released": "DONE"}
        service, states, deliveries = FakeMetadata(), FakeStates(), FakeDeliveries()
        states.upsert("PVTI_1", "PVT_1", "Development", "ACTIVE")
        handle_github_webhook_event(
            event(old="Development", new="Released"), {"X-GitHub-Event": "projects_v2_item"}, metadata_service=service,
            state_repository=states, delivery_repository=deliveries,
            status_mapper=mapper(mapping),
        )
        handle_github_webhook_event(
            event(old="Released", new="Development"), {"X-GitHub-Event": "projects_v2_item"}, metadata_service=service,
            state_repository=states, delivery_repository=deliveries,
            status_mapper=mapper(mapping),
        )
        self.assertEqual(service.completed, ["PVTI_1"])
        self.assertEqual(service.started, ["PVTI_1"])

    def test_duplicate_delivery_is_idempotent(self):
        service, states, deliveries = FakeMetadata(), FakeStates(), FakeDeliveries()
        headers = {"X-GitHub-Delivery": "delivery-1", "X-GitHub-Event": "projects_v2_item"}
        kwargs = dict(metadata_service=service, state_repository=states,
                      delivery_repository=deliveries,
                      status_mapper=mapper({"Todo": "NOT_STARTED", "Doing": "ACTIVE"}))
        payload = event(old="Todo", new="Doing")
        handle_github_webhook_event(payload, headers, **kwargs)
        handle_github_webhook_event(payload, headers, **kwargs)
        self.assertEqual(service.started, ["PVTI_1"])

    def test_authenticated_webhook_fetches_authoritative_status(self):
        service, states = FakeMetadata(), FakeStates()
        states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        payload = event(old="Todo", new="Unrelated single select")
        handle_github_webhook_event(
            payload, {"X-GitHub-Event": "projects_v2_item"}, token="installation-token",
            metadata_service=service, state_repository=states,
            delivery_repository=FakeDeliveries(),
            status_mapper=mapper({"Todo": "NOT_STARTED", "Doing": "ACTIVE"}),
            status_fetcher=lambda item_id, token: "Doing",
        )
        self.assertEqual(service.started, ["PVTI_1"])
        self.assertEqual(states.get("PVTI_1")["status_option_name"], "Doing")

    def test_unsupported_item_is_acknowledged_without_lifecycle(self):
        service, states, deliveries = FakeMetadata(), FakeStates(), FakeDeliveries()
        service.task_started = lambda item_id, token=None: (_ for _ in ()).throw(
            UnsupportedProjectItemError("PullRequest")
        )
        headers = {"X-GitHub-Event": "projects_v2_item", "X-GitHub-Delivery": "unsupported-1"}
        handle_github_webhook_event(
            event(new="Doing"), headers, token="installation-token",
            metadata_service=service, state_repository=states,
            delivery_repository=deliveries,
            status_mapper=mapper({"Doing": "ACTIVE"}),
            status_fetcher=lambda item_id, token: "Doing",
        )
        self.assertTrue(deliveries.is_processed("unsupported-1"))
        self.assertEqual(states.get("PVTI_1")["logical_status"], "ACTIVE")

    def test_missing_or_unrelated_event_header_is_ignored(self):
        service = FakeMetadata()
        kwargs = dict(metadata_service=service, state_repository=FakeStates(),
                      delivery_repository=FakeDeliveries(),
                      status_mapper=mapper({"Doing": "ACTIVE"}))
        handle_github_webhook_event(event(new="Doing"), {}, **kwargs)
        handle_github_webhook_event(event(new="Doing"), {"X-GitHub-Event": "issues"}, **kwargs)
        self.assertEqual(service.started, [])


class SyncAndPaginationTests(unittest.TestCase):
    def test_project_discovery_queries_installation_organization_and_paginates(self):
        responses = [
            {"organization": {"login": "example-org", "projectsV2": {
                "nodes": [{"id": "PVT_1", "number": 1, "title": "First"}],
                "pageInfo": {"hasNextPage": True, "endCursor": "next"},
            }}},
            {"organization": {"login": "example-org", "projectsV2": {
                "nodes": [{"id": "PVT_2", "number": 2, "title": "Second"}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }}},
        ]
        with patch("github_data_collection.project_service.execute_query", side_effect=responses) as execute:
            projects = discover_projects("installation-token", "example-org")
        self.assertEqual([project["number"] for project in projects], [1, 2])
        self.assertIn("organization(login: $login)", execute.call_args_list[0].args[0])
        self.assertEqual(execute.call_args_list[0].args[1]["login"], "example-org")
        self.assertEqual(execute.call_args_list[1].args[1]["cursor"], "next")

    def test_initial_sync_collects_already_active_item(self):
        service, states = FakeMetadata(), FakeStates()

        def fetcher(**kwargs):
            return "PVT_1", [{"project_item_id": "PVTI_ACTIVE", "status": "Development"}]

        initial_sync(fetcher=fetcher, metadata_service=service,
                     state_repository=states,
                     status_mapper=mapper({"Development": "ACTIVE"}))
        self.assertEqual(service.synced, [("PVTI_ACTIVE", None)])
        self.assertEqual(states.get("PVTI_ACTIVE")["logical_status"], "ACTIVE")

    def test_initial_sync_reconciles_stale_active_item_to_inactive(self):
        service, states = FakeMetadata(), FakeStates()
        states.upsert("PVTI_DONE", "PVT_1", "Development", "ACTIVE")

        initial_sync(
            fetcher=lambda **kwargs: (
                "PVT_1", [{"project_item_id": "PVTI_DONE", "status": "Released"}]
            ),
            metadata_service=service,
            state_repository=states,
            status_mapper=mapper({"Development": "ACTIVE", "Released": "DONE"}),
        )

        self.assertEqual(service.inactive, ["PVTI_DONE"])
        self.assertEqual(states.get("PVTI_DONE")["logical_status"], "DONE")

    def test_pagination_returns_more_than_100_items(self):
        def response(start, count, has_next, cursor):
            return {"user": {"projectV2": {"id": "PVT_1", "items": {
                "nodes": [{"id": f"PVTI_{i}", "content": {"id": f"I_{i}"},
                           "fieldValues": {"nodes": [{"field": {"name": "Status"}, "name": "Todo"}]}}
                          for i in range(start, start + count)],
                "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
            }}}}

        with patch("github_data_collection.collectors.status_monitor.execute_query", side_effect=[
            response(0, 100, True, "cursor-100"),
            response(100, 25, False, None),
        ]) as query:
            project_id, items = fetch_all_project_items(owner="owner", number=1)
        self.assertEqual(project_id, "PVT_1")
        self.assertEqual(len(items), 125)
        self.assertEqual(query.call_args_list[1].args[1]["cursor"], "cursor-100")


if __name__ == "__main__":
    unittest.main()
