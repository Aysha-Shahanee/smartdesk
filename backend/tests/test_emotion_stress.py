"""The stress derivation over recorded emotion blocks."""

import unittest

from app.services import emotion_stress_service as stress


def _block(angry=0.0, happy=0.0, neutral=0.0, surprise=0.0, frames=900,
           minutes=15.0, start="2026-08-16T09:00:00+05:30",
           end="2026-08-16T09:15:00+05:30", dominant="Neutral"):
    return {
        "block_start_time": start,
        "block_end_time": end,
        "duration_minutes": minutes,
        "dominant_emotion": dominant,
        "processed_frame_count": frames,
        "emotion_scores": {
            "Angry": angry, "Happy": happy, "Neutral": neutral, "Surprise": surprise
        },
    }


class BlockStressTests(unittest.TestCase):
    def test_an_all_neutral_block_sits_at_the_resting_baseline(self):
        score = stress.block_stress(_block(neutral=1.0))
        self.assertAlmostEqual(score, stress.RESTING_SCORE, places=6)

    def test_happiness_reads_below_the_resting_baseline(self):
        self.assertLess(stress.block_stress(_block(happy=1.0)), stress.RESTING_SCORE)

    def test_anger_reads_well_above_it(self):
        self.assertGreater(stress.block_stress(_block(angry=1.0)), 0.9)

    def test_happiness_buffers_the_same_amount_of_anger(self):
        """The point of subtracting Happy rather than ignoring it."""
        with_happy = stress.block_stress(_block(angry=0.3, happy=0.6, neutral=0.1))
        with_neutral = stress.block_stress(_block(angry=0.3, happy=0.0, neutral=0.7))
        self.assertLess(with_happy, with_neutral)

    def test_surprise_counts_less_than_anger(self):
        self.assertLess(
            stress.block_stress(_block(surprise=1.0)),
            stress.block_stress(_block(angry=1.0)),
        )

    def test_a_block_that_saw_no_frames_has_no_score(self):
        self.assertIsNone(stress.block_stress(_block(angry=1.0, frames=0)))

    def test_few_frames_shrink_toward_the_baseline(self):
        confident = stress.block_stress(_block(angry=0.6, neutral=0.4, frames=900))
        sparse = stress.block_stress(_block(angry=0.6, neutral=0.4, frames=10))
        self.assertGreater(confident, sparse)
        self.assertLess(abs(sparse - stress.RESTING_SCORE), abs(confident - stress.RESTING_SCORE))

    def test_shrinkage_never_flips_the_direction(self):
        """A sparse calm block must not read as stressed, and vice versa."""
        self.assertLess(stress.block_stress(_block(happy=1.0, frames=3)), stress.RESTING_SCORE)
        self.assertGreater(stress.block_stress(_block(angry=1.0, frames=3)), stress.RESTING_SCORE)

    def test_scores_stay_inside_the_scale(self):
        for block in (_block(angry=1.0), _block(happy=1.0), _block(surprise=1.0),
                      _block(angry=0.5, surprise=0.5)):
            score = stress.block_stress(block)
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class StressSeriesTests(unittest.TestCase):
    def test_points_come_back_oldest_first(self):
        blocks = [
            _block(neutral=1.0, start="2026-08-16T11:00:00+05:30"),
            _block(neutral=1.0, start="2026-08-16T09:00:00+05:30"),
            _block(neutral=1.0, start="2026-08-16T10:00:00+05:30"),
        ]
        starts = [p.block_start_time for p in stress.stress_series(blocks)]
        self.assertEqual(starts, sorted(starts))

    def test_blocks_without_frames_are_skipped(self):
        blocks = [_block(neutral=1.0), _block(neutral=1.0, frames=0)]
        self.assertEqual(len(stress.stress_series(blocks)), 1)

    def test_empty_input_yields_no_points(self):
        self.assertEqual(stress.stress_series([]), [])


class StressSummaryTests(unittest.TestCase):
    def test_no_blocks_means_no_score_rather_than_zero(self):
        summary = stress.stress_summary([])
        self.assertIsNone(summary.score)
        self.assertEqual(summary.block_count, 0)
        self.assertIsNone(summary.driver)

    def test_blocks_that_saw_nothing_do_not_count_as_calm(self):
        summary = stress.stress_summary([_block(neutral=1.0, frames=0)])
        self.assertIsNone(summary.score)

    def test_a_short_tail_block_cannot_swing_the_day(self):
        calm_day = [_block(neutral=1.0, minutes=15.0) for _ in range(8)]
        spike = _block(angry=1.0, minutes=1.0, frames=20)

        without = stress.stress_summary(calm_day).score
        with_spike = stress.stress_summary(calm_day + [spike]).score

        self.assertLessEqual(with_spike - without, 3)

    def test_summary_reports_observed_minutes_and_block_count(self):
        summary = stress.stress_summary([
            _block(neutral=1.0, minutes=15.0),
            _block(neutral=1.0, minutes=7.5),
        ])
        self.assertEqual(summary.block_count, 2)
        self.assertAlmostEqual(summary.observed_minutes, 22.5, places=1)

    def test_driver_names_the_emotion_that_contributed_most_tension(self):
        angry_day = stress.stress_summary([_block(angry=0.6, neutral=0.4)])
        happy_day = stress.stress_summary([_block(happy=0.9, neutral=0.1)])
        self.assertEqual(angry_day.driver, "Angry")
        self.assertEqual(happy_day.driver, "Happy")

    def test_a_sustained_angry_day_scores_above_a_calm_one(self):
        calm = stress.stress_summary([_block(neutral=1.0) for _ in range(6)]).score
        tense = stress.stress_summary([_block(angry=0.5, neutral=0.5) for _ in range(6)]).score
        self.assertGreater(tense, calm)


if __name__ == "__main__":
    unittest.main()
