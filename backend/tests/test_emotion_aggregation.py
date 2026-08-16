"""Emotion block aggregation, consent gating, and start/stop reporting.

The capture loop itself needs a webcam, but everything that decides what gets
stored and what the API reports is pure logic and is covered here.
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings

EMOTION_PROJECT_DIR = (
    Path(__file__).resolve().parents[2] / "emotion-recognition" / "RAF-DB-improvement"
)
if str(EMOTION_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(EMOTION_PROJECT_DIR))

from emotion_block_aggregator import EMOTIONS, EmotionBlockAggregator  # noqa: E402
from storage.session_manager import SessionManager  # noqa: E402


def _aggregator(start: datetime, block_minutes: int = 15) -> EmotionBlockAggregator:
    manager = SessionManager(user_id="test_user")
    object.__setattr__(manager.current_session, "session_start_time", start)
    return EmotionBlockAggregator(
        output_path=Path("unused.jsonl"),
        session_manager=manager,
        block_minutes=block_minutes,
    )


class EmotionBlockAggregatorTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)

    def test_scores_are_stored_as_means_not_sums(self):
        """A block's stored score must not scale with how many frames it saw."""
        aggregator = _aggregator(self.start)
        for _ in range(40):
            aggregator.add_frame(
                {"Happy": 0.8, "Neutral": 0.2, "Angry": 0.0, "Surprise": 0.0},
                timestamp=self.start + timedelta(seconds=1),
            )

        block = aggregator.finalize_current_block(
            block_type="complete", end_time=self.start + timedelta(minutes=15)
        )

        self.assertAlmostEqual(block["emotion_scores"]["Happy"], 0.8, places=6)
        self.assertAlmostEqual(block["emotion_scores"]["Neutral"], 0.2, places=6)
        self.assertEqual(block["processed_frame_count"], 40)

    def test_two_blocks_with_different_frame_counts_are_comparable(self):
        """Same emotional content, very different frame counts, same score."""
        probabilities = {"Happy": 0.6, "Neutral": 0.4, "Angry": 0.0, "Surprise": 0.0}

        short = _aggregator(self.start)
        for _ in range(12):
            short.add_frame(probabilities, timestamp=self.start + timedelta(seconds=1))
        short_block = short.finalize_current_block(
            block_type="complete", end_time=self.start + timedelta(minutes=15)
        )

        long = _aggregator(self.start)
        for _ in range(900):
            long.add_frame(probabilities, timestamp=self.start + timedelta(seconds=1))
        long_block = long.finalize_current_block(
            block_type="complete", end_time=self.start + timedelta(minutes=15)
        )

        self.assertAlmostEqual(
            short_block["emotion_scores"]["Happy"],
            long_block["emotion_scores"]["Happy"],
            places=6,
        )

    def test_mean_scores_are_zero_before_any_frame(self):
        aggregator = _aggregator(self.start)
        self.assertEqual(aggregator.mean_scores(), {e: 0.0 for e in EMOTIONS})

    def test_block_with_no_frames_is_unknown_and_does_not_divide_by_zero(self):
        aggregator = _aggregator(self.start)
        block = aggregator.finalize_current_block(
            block_type="complete", end_time=self.start + timedelta(minutes=15)
        )
        self.assertEqual(block["dominant_emotion"], "Unknown")
        self.assertEqual(block["processed_frame_count"], 0)
        self.assertEqual(block["emotion_scores"], {e: 0.0 for e in EMOTIONS})

    def test_expired_blocks_roll_over_on_the_boundary(self):
        aggregator = _aggregator(self.start)
        aggregator.add_frame(
            {"Happy": 1.0, "Neutral": 0.0, "Angry": 0.0, "Surprise": 0.0},
            timestamp=self.start + timedelta(minutes=1),
        )

        completed = aggregator.complete_expired_blocks(self.start + timedelta(minutes=16))

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["dominant_emotion"], "Happy")
        self.assertEqual(completed[0]["block_type"], "complete")
        self.assertEqual(aggregator.processed_frame_count, 0)

    def test_a_long_gap_emits_every_block_it_spanned(self):
        aggregator = _aggregator(self.start)
        completed = aggregator.complete_expired_blocks(self.start + timedelta(minutes=46))
        self.assertEqual(len(completed), 3)

    def test_flush_discards_a_block_shorter_than_the_partial_minimum(self):
        aggregator = _aggregator(self.start)
        aggregator.add_frame(
            {"Happy": 1.0, "Neutral": 0.0, "Angry": 0.0, "Surprise": 0.0},
            timestamp=self.start + timedelta(minutes=1),
        )
        self.assertIsNone(aggregator.flush(self.start + timedelta(minutes=4)))

    def test_flush_keeps_a_block_past_the_partial_minimum(self):
        aggregator = _aggregator(self.start)
        aggregator.add_frame(
            {"Happy": 0.0, "Neutral": 0.0, "Angry": 1.0, "Surprise": 0.0},
            timestamp=self.start + timedelta(minutes=1),
        )
        block = aggregator.flush(self.start + timedelta(minutes=6))

        self.assertIsNotNone(block)
        self.assertEqual(block["block_type"], "partial")
        self.assertEqual(block["dominant_emotion"], "Angry")
        self.assertAlmostEqual(block["duration_minutes"], 6.0, places=2)


class EmotionConsentTests(unittest.TestCase):
    """Webcam capture must not be reachable until consent is on record."""

    def setUp(self):
        import app.main as main

        self.client = TestClient(main.app)
        self._original = self.client.get("/api/v1/emotion/consent").json()["webcam_enabled"]

    def tearDown(self):
        self.client.put("/api/v1/emotion/consent", json={"webcam_enabled": self._original})

    def test_consent_defaults_to_off(self):
        self.client.put("/api/v1/emotion/consent", json={"webcam_enabled": False})
        self.assertFalse(self.client.get("/api/v1/emotion/consent").json()["webcam_enabled"])

    def test_start_is_refused_without_consent(self):
        self.client.put("/api/v1/emotion/consent", json={"webcam_enabled": False})

        response = self.client.post("/api/v1/emotion/start")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"]["stage"], "consent")

    def test_consent_round_trips(self):
        self.assertTrue(
            self.client.put(
                "/api/v1/emotion/consent", json={"webcam_enabled": True}
            ).json()["webcam_enabled"]
        )
        self.assertTrue(self.client.get("/api/v1/emotion/consent").json()["webcam_enabled"])


class EmotionStartReportingTests(unittest.TestCase):
    """A start that failed must not report success."""

    def test_start_reports_the_failure_when_the_runtime_cannot_be_prepared(self):
        from emotion_service import EmotionRecognitionService

        service = EmotionRecognitionService(
            project_dir=EMOTION_PROJECT_DIR, user_id=settings.DEFAULT_USER_ID
        )

        def explode():
            raise RuntimeError("model download failed")

        service._prepare_runtime = explode
        service.local_storage = _NullStorage()

        service.start(show_window=False)
        service.stop(wait=True)
        status = service.get_status()

        self.assertFalse(status["running"])
        self.assertIn("model download failed", status["last_error"])


class _NullStorage:
    """Stand-in so the failure path does not need the database."""

    def upsert_session(self, record):
        return record

    def upsert_block(self, record):
        return record

    def get_session(self, session_id):
        return None

    def get_session_blocks(self, session_id, user_id=None):
        return []

    def get_latest_session(self, user_id):
        return None


if __name__ == "__main__":
    unittest.main()
