import sys
import time
import unittest
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
SMARTDESK_V2_ROOT = PROJECT_ROOT / "emotion-recognition" / "smartdesk_v2"
if str(SMARTDESK_V2_ROOT) not in sys.path:
    sys.path.insert(0, str(SMARTDESK_V2_ROOT))

from app.core.database import Base
from app.models.db.smartdesk_detection import (
    SmartDeskDetectionSessionRecord,
    SmartDeskFinalStateBlockRecord,
    SmartDeskReportingBlockRecord,
    SmartDeskSignalBlockRecord,
)
from app.repositories.smartdesk_detection_repository import SmartDeskDetectionRepository
from app.services.smartdesk_detection_sql_store import SmartDeskSqlBlockStore
from src.emotion.temporal import EmotionBlockSummary
from src.service import SmartDeskEmotionService

import src.service as service_module


class FakeCapture:
    def __init__(self, index):
        self.index = index

    def isOpened(self):
        return True

    def read(self):
        return True, object()

    def release(self):
        pass


class FakePipeline:
    wrote_signal = False

    def __init__(self, **kwargs):
        self.store = kwargs.get("store")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        pass

    def process_frame(self, frame, timestamp):
        if self.store is not None and not FakePipeline.wrote_signal:
            FakePipeline.wrote_signal = True
            self.store.append_emotion(_emotion_summary())
        detection = SimpleNamespace(face_detected=True)
        result = SimpleNamespace(detection=detection)
        return SimpleNamespace(
            frame_result=result,
            emotion_block=None,
            engagement_block=None,
            sleepiness_block=None,
        )

    def flush_until(self, timestamp):
        return SimpleNamespace(
            emotion_blocks=[],
            engagement_blocks=[],
            sleepiness_blocks=[],
        )


@dataclass
class FakeSchedule:
    real_start_offset_seconds: float
    real_start: datetime
    landmark_state: object
    full_system: object


class SmartDeskSqlStoreTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        FakePipeline.wrote_signal = False

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_sql_store_writes_and_reads_signal_block(self):
        repo = SmartDeskDetectionRepository(self.db)
        store = SmartDeskSqlBlockStore(repo, user_id="test-user", session_id="test-session")

        store.append_emotion(_emotion_summary())

        rows = store.read_blocks("emotion")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].summary["top_class"], "Happy")
        self.assertEqual(self.db.query(SmartDeskSignalBlockRecord).count(), 1)

    def test_sql_store_can_open_short_lived_sessions_from_factory(self):
        store = SmartDeskSqlBlockStore(
            user_id="test-user",
            session_id="factory-session",
            session_factory=self.SessionLocal,
        )

        store.append_emotion(_emotion_summary())

        rows = store.read_blocks("emotion")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].summary["top_class"], "Happy")
        self.assertEqual(self.db.query(SmartDeskSignalBlockRecord).count(), 1)

    def test_service_writes_signal_and_session_through_sql_store(self):
        original_schedule = service_module.build_smartdesk_session_schedule
        original_first_end = service_module.first_block_end_offset_seconds
        original_end = service_module.choose_real_end_time
        try:
            service_module.build_smartdesk_session_schedule = lambda warmup_end: FakeSchedule(
                real_start_offset_seconds=0.0,
                real_start=warmup_end,
                landmark_state=None,
                full_system=None,
            )
            service_module.first_block_end_offset_seconds = lambda *args, **kwargs: 9999.0
            service_module.choose_real_end_time = lambda actual_end: actual_end

            store = SmartDeskSqlBlockStore(
                user_id="test-user",
                session_id="temporary",
                session_factory=self.SessionLocal,
            )
            service = SmartDeskEmotionService(
                sample_fps=30.0,
                warmup_seconds=0.0,
                capture_factory=FakeCapture,
                pipeline_factory=FakePipeline,
                store=store,
            )

            service.start(seconds=0.5)
            self._wait_for_signal_row()
            status = service.stop(wait=True, timeout_seconds=5.0)

            self.assertFalse(status["running"])
            self.assertEqual(self.db.query(SmartDeskDetectionSessionRecord).count(), 1)
            self.assertEqual(self.db.query(SmartDeskSignalBlockRecord).count(), 1)
            session = self.db.query(SmartDeskDetectionSessionRecord).one()
            signal = self.db.query(SmartDeskSignalBlockRecord).one()
            self.assertEqual(signal.session_id, session.id)
            self.assertEqual(signal.user_id, "test-user")
        finally:
            service_module.build_smartdesk_session_schedule = original_schedule
            service_module.first_block_end_offset_seconds = original_first_end
            service_module.choose_real_end_time = original_end

    def _wait_for_signal_row(self):
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if self.db.query(SmartDeskSignalBlockRecord).count() >= 1:
                return
            time.sleep(0.02)
        self.fail("Timed out waiting for the fake pipeline to write a SQL signal block")


def _emotion_summary():
    return EmotionBlockSummary(
        start_timestamp=0.0,
        end_timestamp=10.0,
        block_start_time="2026-08-22T09:00:00+05:30",
        block_end_time="2026-08-22T09:00:10+05:30",
        window_seconds=10.0,
        total_time=10.0,
        valid_frame_count=20,
        happy_avg=0.7,
        neutral_avg=0.2,
        confusion_avg=0.1,
        top_class="Happy",
        top_probability=0.7,
        state="happy",
        sublabel="happy",
        ready=True,
    )


if __name__ == "__main__":
    unittest.main()


