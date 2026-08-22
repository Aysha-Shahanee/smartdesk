import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.db.smartdesk_detection import (
    SmartDeskDetectionSessionRecord,
    SmartDeskFinalStateBlockRecord,
    SmartDeskReportingBlockRecord,
    SmartDeskSignalBlockRecord,
)
from app.repositories.smartdesk_detection_repository import SmartDeskDetectionRepository
from app.services import smartdesk_detection_endpoint_service as endpoint_service


class SmartDeskEndpointServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(
            bind=self.engine,
            tables=[
                SmartDeskDetectionSessionRecord.__table__,
                SmartDeskSignalBlockRecord.__table__,
                SmartDeskFinalStateBlockRecord.__table__,
                SmartDeskReportingBlockRecord.__table__,
            ],
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()
        self.repo = SmartDeskDetectionRepository(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_current_session_uses_latest_reporting_blocks(self):
        self._insert_session("older-session", "2026-08-22T08:00:00+05:30")
        self._insert_session("latest-session", "2026-08-22T09:00:00+05:30")
        self._insert_reporting("latest-session")

        response = endpoint_service.current_session_response(
            self.db,
            user_id="test-user",
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["session"]["id"], "latest-session")
        self.assertEqual(response["status"]["current_session_id"], "latest-session")
        self.assertEqual(response["completed_blocks"][0]["dominant_state"], "Focused")
        self.assertEqual(response["completed_blocks"][0]["state_scores"]["Focused"], 1.0)

    def test_workload_risk_response_uses_reporting_blocks_in_window(self):
        self._insert_session("latest-session", "2026-08-22T09:00:00+05:30")
        self._insert_reporting("latest-session")

        response = endpoint_service.workload_risk_response(
            self.db,
            user_id="test-user",
            start=datetime.fromisoformat("2026-08-22T00:00:00+05:30"),
            end=datetime.fromisoformat("2026-08-23T00:00:00+05:30"),
        )

        self.assertEqual(response["summary"]["workload_risk_score"], 20)
        self.assertEqual(response["summary"]["observed_minutes"], 15.0)
        self.assertEqual(len(response["points"]), 1)
        self.assertEqual(response["points"][0]["dominant_state"], "Focused")
        self.assertEqual(response["points"][0]["workload_risk_score"], 20)
        self.assertNotIn("stress", response["points"][0])
        self.assertNotIn("dominant_emotion", response["points"][0])

    def _insert_session(self, session_id: str, real_start_time: str):
        self.repo.upsert_session({
            "id": session_id,
            "user_id": "test-user",
            "status": "completed",
            "program_start_time": real_start_time,
            "warmup_end_time": real_start_time,
            "real_start_time": real_start_time,
            "actual_camera_end_time": "2026-08-22T09:16:00+05:30",
            "usable_block_end_time": "2026-08-22T09:15:00+05:30",
            "discarded_tail_seconds": 60.0,
            "startup_wait_seconds_after_warmup": 0.0,
            "official_seconds_requested": 0.0,
            "sample_fps": 2.0,
            "frames_read": 100,
            "samples_processed": 50,
            "face_detected_samples": 45,
            "completed_counts": {"reporting": 1},
            "created_at": real_start_time,
            "updated_at": real_start_time,
        })

    def _insert_reporting(self, session_id: str):
        self.repo.upsert_reporting_block({
            "id": f"report-{session_id}",
            "user_id": "test-user",
            "session_id": session_id,
            "summary": {
                "start_timestamp": 0.0,
                "end_timestamp": 900.0,
                "block_start_time": "2026-08-22T09:00:00+05:30",
                "block_end_time": "2026-08-22T09:15:00+05:30",
                "window_seconds": 900.0,
                "final_state_block_count": 3,
                "focused_ratio": 1.0,
                "struggling_ratio": 0.0,
                "disengaged_ratio": 0.0,
                "fatigued_ratio": 0.0,
                "overloaded_ratio": 0.0,
                "dominant_state": "focused",
                "ready": True,
            },
            "created_at": "2026-08-22T09:15:00+05:30",
        })


if __name__ == "__main__":
    unittest.main()
