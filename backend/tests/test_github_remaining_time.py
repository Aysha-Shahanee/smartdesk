import unittest

from app.services.github_remaining_time_service import GitHubRemainingTimeService


def trusted_time(hours, attribution="repository_match"):
    return {
        "time_spent_hours": hours,
        "time_attribution_status": attribution,
        "data_status": "complete",
    }


class GitHubRemainingTimeTests(unittest.TestCase):
    def test_subtracts_authoritative_time_spent(self):
        result = GitHubRemainingTimeService.calculate(20, trusted_time(5))
        self.assertEqual(result.remaining_time_hours, 15)
        self.assertEqual(result.remaining_time_status, "baseline_available")
        self.assertIsNone(result.overrun_hours)
        self.assertFalse(result.approaching_initial_estimate)

    def test_live_scale_repository_match_keeps_remaining_estimate_available(self):
        result = GitHubRemainingTimeService.calculate(
            20.6, trusted_time(11 / 60)
        )
        self.assertAlmostEqual(result.remaining_time_hours, 20.4166666667)
        self.assertEqual(result.remaining_time_status, "baseline_available")

    def test_preserved_historical_time_remains_usable_after_repository_ambiguity(self):
        result = GitHubRemainingTimeService.calculate(
            2, trusted_time(35 / 60, "branch_match")
        )

        self.assertAlmostEqual(result.remaining_time_hours, 85 / 60)
        self.assertEqual(result.remaining_time_status, "baseline_available")

    def test_zero_spent_preserves_initial_estimate(self):
        self.assertEqual(
            GitHubRemainingTimeService.calculate(20, trusted_time(0)).remaining_time_hours,
            20,
        )

    def test_subtracts_complete_branch_matched_time_spent(self):
        result = GitHubRemainingTimeService.calculate(
            20, trusted_time(2.5, "branch_match")
        )
        self.assertEqual(result.remaining_time_hours, 17.5)
        self.assertEqual(result.remaining_time_status, "baseline_available")

    def test_branch_match_overrun_is_explicitly_reported(self):
        result = GitHubRemainingTimeService.calculate(
            20, trusted_time(23, "branch_match")
        )
        self.assertIsNone(result.remaining_time_hours)
        self.assertEqual(result.remaining_time_status, "estimate_exceeded")
        self.assertEqual(result.overrun_hours, 3)

    def test_equal_or_exceeded_estimate_is_explicitly_reported(self):
        equal = GitHubRemainingTimeService.calculate(20, trusted_time(20))
        exceeded = GitHubRemainingTimeService.calculate(20, trusted_time(25))
        self.assertIsNone(equal.remaining_time_hours)
        self.assertEqual(equal.remaining_time_status, "estimate_exceeded")
        self.assertEqual(equal.overrun_hours, 0)
        self.assertIsNone(exceeded.remaining_time_hours)
        self.assertEqual(exceeded.remaining_time_status, "estimate_exceeded")
        self.assertEqual(exceeded.overrun_hours, 5)

    def test_completed_lifecycle_has_zero_remaining(self):
        result = GitHubRemainingTimeService.calculate(
            None, {"time_spent_hours": None}, lifecycle_status="DONE"
        )
        self.assertEqual(result.remaining_time_hours, 0)
        self.assertEqual(result.remaining_time_status, "completed")
        self.assertIsNone(result.overrun_hours)

    def test_marks_active_task_approaching_initial_estimate_at_ninety_percent(self):
        below = GitHubRemainingTimeService.calculate(20, trusted_time(17.9))
        approaching = GitHubRemainingTimeService.calculate(20, trusted_time(18))
        self.assertFalse(below.approaching_initial_estimate)
        self.assertTrue(approaching.approaching_initial_estimate)

    def test_ambiguous_unavailable_or_partial_time_spent_is_not_subtracted(self):
        for time_spent in (
            {**trusted_time(5), "time_attribution_status": "ambiguous"},
            {**trusted_time(None), "time_attribution_status": "no_match"},
            {**trusted_time(5), "data_status": "partial"},
            {**trusted_time(5, "branch_match"), "data_status": "partial"},
        ):
            result = GitHubRemainingTimeService.calculate(20, time_spent)
            self.assertIsNone(result.remaining_time_hours)
            self.assertEqual(result.remaining_time_status, "time_spent_unavailable")

    def test_missing_initial_prediction_is_unavailable(self):
        result = GitHubRemainingTimeService.calculate(None, trusted_time(5))
        self.assertIsNone(result.remaining_time_hours)
        self.assertEqual(result.remaining_time_status, "initial_prediction_unavailable")

    def test_repeated_recalculation_is_deterministic_and_new_activity_decreases_value(self):
        first = GitHubRemainingTimeService.calculate(20, trusted_time(5))
        repeated = GitHubRemainingTimeService.calculate(20, trusted_time(5))
        after_new_activity = GitHubRemainingTimeService.calculate(20, trusted_time(6))
        self.assertEqual(first, repeated)
        self.assertEqual(after_new_activity.remaining_time_hours, 14)


if __name__ == "__main__":
    unittest.main()
