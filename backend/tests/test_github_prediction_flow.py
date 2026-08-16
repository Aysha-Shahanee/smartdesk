import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.db import ActivitySegmentRecord, IDESessionRecord
from app.models.db.github import GitHubInitialPredictionRecord
from app.services.github_prediction_service import GitHubPredictionService
from github_data_collection.database import Base as CollectorBase, CollectedTask
from github_data_collection.initial_sync import initial_sync
from github_data_collection.repositories import CollectedTaskRepository
from github_data_collection.task_metadata_service import TaskMetadataService
from github_data_collection.webhook_handler import handle_github_webhook_event


class FakePredictor:
    def __init__(self, failure=None):
        self.calls = 0
        self.failure = failure

    def predict(self, metadata):
        self.calls += 1
        if self.failure:
            raise self.failure
        return {"low_hours": 1.0, "typical_hours": 4.0, "high_hours": 12.0, "model_version": "test-v1"}


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
        self.rows[item_id] = {"status_option_name": name, "logical_status": logical, "project_id": project_id}


class FakeDeliveries:
    def __init__(self):
        self.ids = set()

    def is_processed(self, delivery_id):
        return bool(delivery_id and delivery_id in self.ids)

    def mark_processed(self, delivery_id):
        if delivery_id:
            self.ids.add(delivery_id)


class GitHubPredictionFlowTests(unittest.TestCase):
    def setUp(self):
        smart_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            smart_engine,
            tables=[
                GitHubInitialPredictionRecord.__table__,
                IDESessionRecord.__table__,
                ActivitySegmentRecord.__table__,
            ],
        )
        self.smart_session = sessionmaker(bind=smart_engine)()
        collector_engine = create_engine("sqlite:///:memory:")
        CollectorBase.metadata.create_all(collector_engine)
        collector_sessions = sessionmaker(bind=collector_engine, expire_on_commit=False)
        self.collected = CollectedTaskRepository(session_factory=collector_sessions)
        self.active = FakeActive()
        self.states = FakeStates()
        self.deliveries = FakeDeliveries()
        self.predictor = FakePredictor()
        prediction_service = GitHubPredictionService(self.smart_session, self.predictor)
        self.metadata_service = TaskMetadataService(
            collected=self.collected,
            active=self.active,
            fetcher=lambda item_id, token=None: {
                "project_item_id": item_id,
                "issue_id": "I_1",
                "issue_number": 42,
                "title": "Fix issue",
                "description": "Description",
                "labels": ["bug"],
                "repository": "microsoft/vscode",
                "smartdesk_user_id": "user-one",
                "project_id": "PVT_1",
                "detected_start_time": "2026-08-10T10:00:00Z",
            },
            on_lifecycle_started=prediction_service.predict_initial,
        )
        self.mapping = lambda project_id, name: {"Todo": "NOT_STARTED", "Doing": "ACTIVE", "Done": "DONE"}.get(name, "OTHER")

    def event(self, new):
        return {"projects_v2_item": {"node_id": "PVTI_1", "project_node_id": "PVT_1", "status_option_name": new}}

    def deliver(self, new, delivery):
        handle_github_webhook_event(
            self.event(new), {"X-GitHub-Event": "projects_v2_item", "X-GitHub-Delivery": delivery},
            metadata_service=self.metadata_service, state_repository=self.states,
            delivery_repository=self.deliveries, status_mapper=self.mapping,
        )

    def prediction_rows(self):
        return self.smart_session.query(GitHubInitialPredictionRecord).order_by(GitHubInitialPredictionRecord.id).all()

    def test_active_duplicate_done_and_reopened_lifecycles(self):
        self.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.deliver("Doing", "delivery-1")
        self.deliver("Doing", "delivery-1")
        self.deliver("Done", "delivery-2")
        self.assertEqual(self.predictor.calls, 1)
        self.assertEqual(len(self.prediction_rows()), 1)
        self.assertEqual(self.prediction_rows()[0].issue_id, "I_1")
        self.assertEqual(self.prediction_rows()[0].issue_number, 42)
        self.deliver("Doing", "delivery-3")
        self.assertEqual(self.predictor.calls, 2)
        self.assertEqual(len(self.prediction_rows()), 2)

    def test_prediction_failure_is_persisted_without_losing_lifecycle(self):
        failing = FakePredictor(RuntimeError("model unavailable"))
        service = GitHubPredictionService(self.smart_session, failing)
        self.metadata_service.on_lifecycle_started = service.predict_initial
        self.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.deliver("Doing", "delivery-failed")
        row = self.prediction_rows()[0]
        self.assertEqual(row.prediction_status, "failed")
        self.assertIn("model unavailable", row.prediction_error)
        self.assertIn("PVTI_1", self.active.rows)

    def test_user_isolation_in_prediction_lookup(self):
        self.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.deliver("Doing", "delivery-user")
        repository = GitHubPredictionService(self.smart_session, self.predictor).repository
        lifecycle_id = self.prediction_rows()[0].collector_lifecycle_id
        self.assertIn(lifecycle_id, repository.for_open_lifecycles("user-one", [lifecycle_id]))
        self.assertNotIn(lifecycle_id, repository.for_open_lifecycles("user-two", [lifecycle_id]))

    def test_persisted_prediction_is_reused_by_a_new_service_instance(self):
        self.states.upsert("PVTI_1", "PVT_1", "Todo", "NOT_STARTED")
        self.deliver("Doing", "delivery-persisted")
        lifecycle_id = self.prediction_rows()[0].collector_lifecycle_id

        fresh_service = GitHubPredictionService(self.smart_session, FakePredictor())
        persisted = fresh_service.repository.for_open_lifecycles(
            "user-one", [lifecycle_id]
        )[lifecycle_id]

        self.assertEqual(persisted.prediction_status, "succeeded")
        self.assertEqual(persisted.predicted_typical_hours, 4.0)
        self.assertEqual(persisted.model_version, "test-v1")

    def test_repeated_initial_sync_predicts_already_active_task_once(self):
        fetcher = lambda **kwargs: ("PVT_1", [{"project_item_id": "PVTI_1", "status": "Doing"}])
        for _ in range(2):
            initial_sync(
                fetcher=fetcher,
                metadata_service=self.metadata_service,
                state_repository=self.states,
                status_mapper=self.mapping,
            )
        self.assertEqual(self.predictor.calls, 1)
        self.assertEqual(len(self.prediction_rows()), 1)

    def test_active_to_not_started_closes_lifecycle_and_removes_active_task(self):
        self.states.upsert("PVTI_1", "PVT_1", "Doing", "ACTIVE")
        self.metadata_service.task_started("PVTI_1")
        self.deliver("Todo", "delivery-not-started")

        with self.collected.session_factory() as session:
            lifecycle = session.query(CollectedTask).one()
            self.assertIsNotNone(lifecycle.completed_at)
        self.assertNotIn("PVTI_1", self.active.rows)
        self.assertEqual(len(self.prediction_rows()), 1)

    def test_reconciliation_repairs_missed_done_and_is_idempotent(self):
        self.states.upsert("PVTI_1", "PVT_1", "Doing", "ACTIVE")
        self.metadata_service.task_started("PVTI_1")
        fetcher = lambda **kwargs: (
            "PVT_1", [{"project_item_id": "PVTI_1", "status": "Done"}]
        )

        for _ in range(2):
            initial_sync(
                fetcher=fetcher,
                metadata_service=self.metadata_service,
                state_repository=self.states,
                status_mapper=self.mapping,
            )

        with self.collected.session_factory() as session:
            rows = session.query(CollectedTask).all()
            self.assertEqual(len(rows), 1)
            self.assertIsNotNone(rows[0].completed_at)
        self.assertNotIn("PVTI_1", self.active.rows)
        self.assertEqual(len(self.prediction_rows()), 1)

    def test_active_tasks_response_includes_time_spent_contract(self):
        task = {
            "collector_lifecycle_id": 99,
            "project_item_id": "PVTI_99",
            "issue_id": "I_99",
            "title": "Task",
            "started_at": "2026-08-14T10:00:00Z",
            "project_id": "PVT_1",
            "repository": "owner/repo",
            "user_id": "user-one",
        }
        with patch(
            "app.services.github_prediction_service.ActiveTaskRepository.list_for_user",
            return_value=[task],
        ):
            result = GitHubPredictionService(self.smart_session, self.predictor).active_tasks(
                "user-one", "PVT_1"
            )[0]
        self.assertIn("task_active_seconds", result)
        self.assertIn("time_spent_hours", result)
        self.assertIn("time_attribution_status", result)
        self.assertIsNone(result["time_spent_hours"])
        self.assertIsNone(result["remaining_time_hours"])
        self.assertEqual(result["remaining_time_status"], "initial_prediction_unavailable")

    def test_active_tasks_response_calculates_remaining_time_from_backend_values(self):
        task = {
            "collector_lifecycle_id": 100,
            "project_item_id": "PVTI_100",
            "issue_id": "I_100",
            "title": "Task",
            "started_at": "2026-08-14T10:00:00Z",
            "project_id": "PVT_1",
            "repository": "owner/repo",
        }
        self.smart_session.add(GitHubInitialPredictionRecord(
            collector_lifecycle_id=100,
            user_id="user-one",
            project_id="PVT_1",
            project_item_id="PVTI_100",
            issue_id="I_100",
            repository="owner/repo",
            started_at=task["started_at"],
            predicted_typical_hours=20,
            predicted_at="2026-08-14T10:00:01Z",
            prediction_status="succeeded",
        ))
        self.smart_session.commit()

        time_result = Mock()
        time_result.to_dict.return_value = {
            "task_active_seconds": 18000,
            "time_spent_hours": 2.5,
            "time_attribution_status": "branch_match",
            "calculated_through": "2026-08-14T12:00:00Z",
            "data_status": "complete",
        }
        with patch(
            "app.services.github_prediction_service.ActiveTaskRepository.list_for_user",
            return_value=[task],
        ), patch(
            "app.services.github_prediction_service.GitHubTaskTimeSpentService.calculate",
            return_value=time_result,
        ):
            result = GitHubPredictionService(self.smart_session, self.predictor).active_tasks(
                "user-one", "PVT_1"
            )[0]

        self.assertEqual(result["time_spent_hours"], 2.5)
        self.assertEqual(result["time_attribution_status"], "branch_match")
        self.assertEqual(result["remaining_time_hours"], 17.5)
        self.assertEqual(result["remaining_time_status"], "baseline_available")
        self.assertIsNone(result["overrun_hours"])
        self.assertFalse(result["approaching_initial_estimate"])

    def test_active_tasks_response_reports_estimate_overrun_without_zero_remaining(self):
        task = {
            "collector_lifecycle_id": 101,
            "project_item_id": "PVTI_101",
            "issue_id": "I_101",
            "title": "Overrun task",
            "started_at": "2026-08-14T10:00:00Z",
            "project_id": "PVT_1",
            "repository": "owner/repo",
        }
        self.smart_session.add(GitHubInitialPredictionRecord(
            collector_lifecycle_id=101,
            user_id="user-one",
            project_id="PVT_1",
            project_item_id="PVTI_101",
            issue_id="I_101",
            repository="owner/repo",
            started_at=task["started_at"],
            predicted_typical_hours=20,
            predicted_at="2026-08-14T10:00:01Z",
            prediction_status="succeeded",
        ))
        self.smart_session.commit()

        time_result = Mock()
        time_result.to_dict.return_value = {
            "task_active_seconds": 82800,
            "time_spent_hours": 23,
            "time_attribution_status": "branch_match",
            "calculated_through": "2026-08-15T12:00:00Z",
            "data_status": "complete",
        }
        with patch(
            "app.services.github_prediction_service.ActiveTaskRepository.list_for_user",
            return_value=[task],
        ), patch(
            "app.services.github_prediction_service.GitHubTaskTimeSpentService.calculate",
            return_value=time_result,
        ):
            result = GitHubPredictionService(self.smart_session, self.predictor).active_tasks(
                "user-one", "PVT_1"
            )[0]

        self.assertIsNone(result["remaining_time_hours"])
        self.assertEqual(result["remaining_time_status"], "estimate_exceeded")
        self.assertEqual(result["overrun_hours"], 3)
        self.assertFalse(result["approaching_initial_estimate"])


if __name__ == "__main__":
    unittest.main()
