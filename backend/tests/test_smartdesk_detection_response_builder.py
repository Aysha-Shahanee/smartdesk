import unittest

from app.services import smartdesk_detection_response_builder as builder


def _reporting_block(**overrides):
    block = {
        "block_start_time": "2026-08-21T09:00:00+05:30",
        "block_end_time": "2026-08-21T09:15:00+05:30",
        "final_state_block_count": 3,
        "focused_ratio": 1.0,
        "struggling_ratio": 0.0,
        "disengaged_ratio": 0.0,
        "fatigued_ratio": 0.0,
        "overloaded_ratio": 0.0,
        "dominant_state": "focused",
        "ready": True,
    }
    block.update(overrides)
    return block


class StateNormalizationTests(unittest.TestCase):
    def test_normalizes_internal_state_names_for_api(self):
        self.assertEqual(builder.normalize_state("focused"), "Focused")
        self.assertEqual(builder.normalize_state("overloaded"), "Overloaded")
        self.assertEqual(builder.normalize_state("needs-review"), "needs-review")


class SessionResponseTests(unittest.TestCase):
    def test_reporting_blocks_use_clean_state_fields(self):
        response = builder.build_current_session_response(
            status={"running": True, "session_id": "s1"},
            session={"id": "s1"},
            reporting_blocks=[_reporting_block()],
        )
        block = response["completed_blocks"][0]
        self.assertEqual(block["dominant_state"], "Focused")
        self.assertEqual(block["state_scores"]["Focused"], 1.0)
        self.assertNotIn("dominant_emotion", block)
        self.assertNotIn("emotion_scores", block)
        self.assertNotIn("processed_frame_count", block)

    def test_falls_back_to_final_state_blocks_when_no_reporting_blocks_exist(self):
        response = builder.build_current_session_response(
            status={"running": False},
            session={"id": "s1"},
            final_state_blocks=[{
                "block_start_time": "2026-08-21T09:00:00+05:30",
                "block_end_time": "2026-08-21T09:05:00+05:30",
                "state": "fatigued",
                "ready": True,
            }],
        )
        block = response["completed_blocks"][0]
        self.assertEqual(block["dominant_state"], "Fatigued")
        self.assertEqual(block["state_scores"]["Fatigued"], 1.0)
        self.assertNotIn("dominant_emotion", block)
        self.assertNotIn("emotion_scores", block)


class WorkloadRiskTests(unittest.TestCase):
    def test_focused_block_has_low_workload_risk(self):
        point = builder.reporting_block_to_workload_point(_reporting_block())
        self.assertEqual(point.workload_risk_score, 20)
        self.assertEqual(point.confidence, 1.0)
        self.assertEqual(point.duration_minutes, 15.0)
        self.assertEqual(point.dominant_state, "Focused")

    def test_overloaded_block_has_high_workload_risk(self):
        point = builder.reporting_block_to_workload_point(_reporting_block(
            focused_ratio=0,
            overloaded_ratio=1,
            dominant_state="overloaded",
        ))
        self.assertEqual(point.workload_risk_score, 90)
        self.assertEqual(point.dominant_state, "Overloaded")

    def test_period_summary_is_weighted_by_duration_and_confidence(self):
        response = builder.build_workload_risk_response(
            from_time="2026-08-21T00:00:00+05:30",
            to_time="2026-08-22T00:00:00+05:30",
            reporting_blocks=[
                _reporting_block(),
                _reporting_block(
                    block_start_time="2026-08-21T09:15:00+05:30",
                    block_end_time="2026-08-21T09:30:00+05:30",
                    focused_ratio=0,
                    overloaded_ratio=1,
                    dominant_state="overloaded",
                ),
            ],
        )
        self.assertEqual(response["summary"]["workload_risk_score"], 55)
        self.assertEqual(response["summary"]["observed_minutes"], 30.0)
        self.assertEqual(response["summary"]["block_count"], 2)
        self.assertEqual(response["summary"]["driver_state"], "Focused")
        self.assertNotIn("score", response["summary"])
        self.assertNotIn("driver", response["summary"])
        self.assertEqual(len(response["points"]), 2)
        self.assertIn("workload_risk_score", response["points"][0])
        self.assertIn("dominant_state", response["points"][0])
        self.assertNotIn("stress", response["points"][0])
        self.assertNotIn("dominant_emotion", response["points"][0])


if __name__ == "__main__":
    unittest.main()
