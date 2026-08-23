import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

ROUTE_PATH = Path(__file__).resolve().parents[1] / "app" / "routes" / "emotion.py"
spec = importlib.util.spec_from_file_location("smartdesk_emotion_route_under_test", ROUTE_PATH)
emotion = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(emotion)
class FakeSmartDeskService:
    def __init__(self):
        self.running = False
        self.started = False
        self.stopped = False

    def start(self, *, show_window=False, seconds=None):
        self.started = True
        self.running = True
        return self.get_status()

    def stop(self, *, wait=True, timeout_seconds=10.0):
        self.stopped = True
        self.running = False
        return self.get_status()

    def get_status(self):
        return {
            "running": self.running,
            "camera_ready": self.running,
            "last_error": None,
            "current_session_id": "route-test-session",
        }

    def get_session_history(self):
        return {"sessions": [], "latest_blocks": {}}


class EmotionRouteControlTests(unittest.TestCase):
    def setUp(self):
        self.original_service = emotion._emotion_service
        self.fake_service = FakeSmartDeskService()
        emotion._emotion_service = self.fake_service

    def tearDown(self):
        emotion._emotion_service = self.original_service

    def test_start_uses_smartdesk_service_status_shape(self):
        with patch.object(emotion, "_require_webcam_consent", lambda db: None):
            response = emotion.start_emotion_detection(db=None)

        self.assertTrue(response["ok"])
        self.assertEqual(response["message"], "SmartDesk detection started.")
        self.assertTrue(response["status"]["running"])
        self.assertTrue(self.fake_service.started)

    def test_stop_returns_history_and_not_running_status(self):
        self.fake_service.running = True

        response = emotion.stop_emotion_detection()

        self.assertTrue(response["ok"])
        self.assertEqual(response["message"], "SmartDesk detection stopped.")
        self.assertFalse(response["status"]["running"])
        self.assertIn("session_history", response)
        self.assertTrue(self.fake_service.stopped)

    def test_status_returns_service_status(self):
        self.fake_service.running = True

        response = emotion.get_emotion_status()

        self.assertTrue(response["running"])
        self.assertEqual(response["current_session_id"], "route-test-session")
        self.assertEqual(response["session_id"], "route-test-session")
        self.assertEqual(response["latest_state"], "Unknown")
        self.assertNotIn("latest_emotion", response)
        self.assertTrue(response["model_ready"])


if __name__ == "__main__":
    unittest.main()


