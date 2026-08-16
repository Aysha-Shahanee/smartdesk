import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from github_data_collection.config import MODULE_DIR, Settings
from github_data_collection.database import ActiveTask, Base, CollectedTask
from github_data_collection.collectors.status_monitor import fetch_all_project_items
from github_data_collection.collectors.metadata_collector import UnsupportedProjectItemError, collect
from github_data_collection.initial_sync import initial_sync
from github_data_collection.project_service import discover_projects
from github_data_collection.repositories import ActiveTaskRepository, CollectedTaskRepository
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

    def test_issue_number_is_nullable_and_persisted_without_changing_issue_id(self):
        historical = self.metadata("2026-01-01T10:00:00Z")
        self.repository.insert(historical)
        current = {**self.metadata("2026-01-02T10:00:00Z"), "issue_number": 42}
        current["project_item_id"] = "PVTI_2"
        self.repository.insert(current)

        historical_row, current_row = self.rows()
        self.assertIsNone(historical_row.issue_number)
        self.assertEqual(current_row.issue_id, "I_1")
        self.assertEqual(current_row.issue_number, 42)
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


class MetadataCollectionTests(unittest.TestCase):
    def test_existing_issue_query_fetches_numeric_number(self):
        response = {"node": {
            "content": {
                "__typename": "Issue", "id": "I_kwDO_node", "number": 42,
                "title": "Task", "body": "Body", "state": "OPEN",
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
                "repository": {"nameWithOwner": "owner/repo"},
                "comments": {"totalCount": 0}, "labels": {"nodes": []},
                "assignees": {"nodes": []},
            },
            "fieldValues": {"nodes": []},
        }}
        with patch(
            "github_data_collection.collectors.metadata_collector.execute_query",
            return_value=response,
        ) as execute:
            metadata = collect("PVTI_1", token="installation-token")

        self.assertIn("number", execute.call_args.args[0])
        self.assertEqual(metadata["issue_id"], "I_kwDO_node")
        self.assertEqual(metadata["issue_number"], 42)

    def test_active_lifecycle_exposes_persisted_issue_number(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        metadata = {
            "project_item_id": "PVTI_1", "issue_id": "I_node",
            "issue_number": 42, "title": "Task",
            "detected_start_time": "2026-01-01T10:00:00Z",
            "smartdesk_user_id": "user-one", "project_id": "PVT_1",
            "repository": "owner/repo",
        }
        CollectedTaskRepository(session_factory=sessions).insert(metadata)
        with patch("github_data_collection.repositories.SessionLocal", sessions):
            active = ActiveTaskRepository()
            active.add(metadata)
            lifecycle = active.list_for_user("user-one")[0]

        with sessions() as session:
            self.assertEqual(session.get(ActiveTask, "PVTI_1").issue_number, 42)
        self.assertEqual(lifecycle["issue_number"], 42)


class OwnershipActiveTasks:
    def __init__(self):
        self.rows = {}

    def add(self, metadata):
        self.rows[metadata["project_item_id"]] = dict(metadata)

    def remove(self, project_item_id):
        self.rows.pop(project_item_id, None)


class TaskOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.collected = CollectedTaskRepository(session_factory=self.sessions)
        self.active = OwnershipActiveTasks()
        self.predicted = []
        self.assignees = {}
        self.service = TaskMetadataService(
            collected=self.collected,
            active=self.active,
            fetcher=self.fetch,
            on_lifecycle_started=lambda metadata: self.predicted.append(
                metadata["project_item_id"]
            ),
            connected_github_login="Rashmi",
        )

    def fetch(self, item_id, token=None):
        return {
            "project_item_id": item_id,
            "issue_id": f"I_{item_id}",
            "issue_number": int(item_id.removeprefix("PVTI_")),
            "title": f"Task {item_id}",
            "assignees": self.assignees.get(item_id, []),
            "detected_start_time": "2026-08-16T10:00:00Z",
            "smartdesk_user_id": "user-one",
            "project_id": "PVT_1",
            "repository": "owner/repo",
        }

    def lifecycle_rows(self, item_id=None):
        with self.sessions() as session:
            query = session.query(CollectedTask)
            if item_id:
                query = query.filter(CollectedTask.project_item_id == item_id)
            return query.order_by(CollectedTask.id).all()

    def assert_rejected(self, assignees):
        self.assignees["PVTI_1"] = assignees
        self.service.task_started("PVTI_1")
        self.assertEqual(self.lifecycle_rows(), [])
        self.assertNotIn("PVTI_1", self.active.rows)
        self.assertEqual(self.predicted, [])

    def test_only_connected_user_is_owned_case_insensitively(self):
        self.assignees["PVTI_1"] = ["rashmi"]
        self.service.task_started("PVTI_1")
        self.assertEqual(len(self.lifecycle_rows()), 1)
        self.assertIn("PVTI_1", self.active.rows)
        self.assertEqual(self.predicted, ["PVTI_1"])

    def test_multiple_assignees_including_connected_user_is_owned(self):
        self.assignees["PVTI_1"] = ["teammate123", "RASHMI"]
        self.service.task_started("PVTI_1")
        self.assertEqual(len(self.lifecycle_rows()), 1)

    def test_only_other_user_is_rejected(self):
        self.assert_rejected(["teammate123"])

    def test_multiple_assignees_excluding_connected_user_are_rejected(self):
        self.assert_rejected(["teammate123", "another-user"])

    def test_unassigned_issue_is_rejected(self):
        self.assert_rejected([])

    def test_initial_sync_imports_owned_active_issue_only(self):
        self.assignees.update({
            "PVTI_1": ["rashmi"],
            "PVTI_2": ["teammate123"],
            "PVTI_3": [],
        })
        states = FakeStates()
        initial_sync(
            fetcher=lambda **kwargs: (
                "PVT_1",
                [
                    {"project_item_id": "PVTI_1", "status": "Doing"},
                    {"project_item_id": "PVTI_2", "status": "Doing"},
                    {"project_item_id": "PVTI_3", "status": "Doing"},
                ],
            ),
            metadata_service=self.service,
            state_repository=states,
            status_mapper=mapper({"Doing": "ACTIVE"}),
        )
        self.assertEqual([row.project_item_id for row in self.lifecycle_rows()], ["PVTI_1"])
        self.assertEqual(set(self.active.rows), {"PVTI_1"})
        self.assertEqual(self.predicted, ["PVTI_1"])

    def test_tracked_lifecycle_closes_after_connected_user_is_unassigned(self):
        self.assignees["PVTI_1"] = ["rashmi"]
        self.service.task_started("PVTI_1")
        self.assignees["PVTI_1"] = []
        self.service.task_completed("PVTI_1")
        row = self.lifecycle_rows()[0]
        self.assertIsNotNone(row.completed_at)
        self.assertNotIn("PVTI_1", self.active.rows)

    def test_reopening_requires_current_ownership_and_preserves_history(self):
        self.assignees["PVTI_1"] = ["rashmi"]
        self.service.task_started("PVTI_1")
        self.service.task_completed("PVTI_1")
        self.assignees["PVTI_1"] = ["teammate123"]
        self.service.task_started("PVTI_1")
        self.assertEqual(len(self.lifecycle_rows()), 1)
        self.assignees["PVTI_1"] = ["rashmi", "teammate123"]
        self.service.task_started("PVTI_1")
        rows = self.lifecycle_rows()
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0].completed_at)
        self.assertIsNone(rows[1].completed_at)

    def test_rejected_issue_does_not_affect_owned_active_issue(self):
        self.assignees.update({"PVTI_1": ["rashmi"], "PVTI_2": ["teammate123"]})
        self.service.task_started("PVTI_1")
        self.service.task_started("PVTI_2")
        self.assertEqual([row.project_item_id for row in self.lifecycle_rows()], ["PVTI_1"])
        self.assertEqual(set(self.active.rows), {"PVTI_1"})
        self.assertEqual(self.predicted, ["PVTI_1"])

    def test_webhook_uses_authoritative_assignees_and_stays_idempotent(self):
        states, deliveries = FakeStates(), FakeDeliveries()
        states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.assignees["PVTI_1"] = ["teammate123"]
        headers = {
            "X-GitHub-Event": "projects_v2_item",
            "X-GitHub-Delivery": "ownership-1",
        }
        kwargs = {
            "metadata_service": self.service,
            "state_repository": states,
            "delivery_repository": deliveries,
            "status_mapper": mapper({"Todo": "NOT_STARTED", "Doing": "ACTIVE"}),
        }

        handle_github_webhook_event(event(new="Doing"), headers, **kwargs)
        handle_github_webhook_event(event(new="Doing"), headers, **kwargs)

        self.assertEqual(self.lifecycle_rows(), [])
        self.assertEqual(self.predicted, [])
        self.assertTrue(deliveries.is_processed("ownership-1"))
        self.assertEqual(states.get("PVTI_1")["logical_status"], "ACTIVE")

    def test_done_webhook_closes_owned_lifecycle_after_reassignment(self):
        states, deliveries = FakeStates(), FakeDeliveries()
        states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.assignees["PVTI_1"] = ["rashmi"]
        kwargs = {
            "metadata_service": self.service,
            "state_repository": states,
            "delivery_repository": deliveries,
            "status_mapper": mapper({
                "Todo": "NOT_STARTED", "Doing": "ACTIVE", "Done": "DONE"
            }),
        }
        handle_github_webhook_event(
            event(new="Doing"),
            {"X-GitHub-Event": "projects_v2_item", "X-GitHub-Delivery": "start-1"},
            **kwargs,
        )
        self.assignees["PVTI_1"] = ["teammate123"]
        handle_github_webhook_event(
            event(old="Doing", new="Done"),
            {"X-GitHub-Event": "projects_v2_item", "X-GitHub-Delivery": "done-1"},
            **kwargs,
        )

        self.assertIsNotNone(self.lifecycle_rows()[0].completed_at)
        self.assertNotIn("PVTI_1", self.active.rows)


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

    def test_temporary_status_fetch_failure_leaves_event_retryable(self):
        service, states, deliveries = FakeMetadata(), FakeStates(), FakeDeliveries()
        headers = {"X-GitHub-Delivery": "retry-1", "X-GitHub-Event": "projects_v2_item"}

        with self.assertRaisesRegex(RuntimeError, "temporary failure"):
            handle_github_webhook_event(
                event(new="Doing"), headers, token="installation-token",
                metadata_service=service, state_repository=states,
                delivery_repository=deliveries,
                status_mapper=mapper({"Doing": "ACTIVE"}),
                status_fetcher=lambda item_id, token: (_ for _ in ()).throw(
                    RuntimeError("temporary failure")
                ),
            )

        self.assertFalse(deliveries.is_processed("retry-1"))
        self.assertIsNone(states.get("PVTI_1"))
        self.assertEqual(service.started, [])

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
