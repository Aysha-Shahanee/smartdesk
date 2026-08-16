"""Invariants for the recommendation engine.

The failure mode for this subsystem is not crashing — it is confidently saying
something untrue that nobody notices for months. These tests target that
directly: every rule must be reachable, no rule may ship a claim weaker than
the evidence it declared it needs, and the templates must actually be
satisfiable by the facts their predicates emit.
"""

import unittest
from datetime import datetime, timedelta

from app.services.recommendations.baselines import (
    BLOCK_BRIDGE_SEC,
    BaselineSet,
    Stat,
    build_blocks,
    percentile,
)
from app.services.recommendations.engine import RecommendationEngine
from app.services.recommendations.narrative import fmt_minutes, magnitude, render
from app.services.recommendations.registry import BY_ID, REGISTRY, load_all_rules
from app.services.recommendations.types import (
    Evidence,
    FeatureContext,
    Finding,
    Scope,
)

load_all_rules()

BASE = datetime(2026, 8, 14, 9, 0, 0)


def ctx(days: int = 30, **features) -> FeatureContext:
    """A synthetic snapshot. Rules are pure, so this is all they ever need."""
    return FeatureContext(
        dict(features), as_of=BASE, user_id="test_user", days_of_history=days
    )


def segment(offset_min: float, length_min: float, state: str = "active", focus: float = 0.8):
    start = BASE + timedelta(minutes=offset_min)
    return {
        "start": start,
        "end": start + timedelta(minutes=length_min),
        "duration": length_min * 60.0,
        "state": state,
        "app": "Code",
        "title": "t",
        "detail": None,
        "category": "work",
        "confidence": 1.0,
        "focus": focus,
        "local_date": "2026-08-14",
        "source": "os",
    }


class TestRuleCatalogue(unittest.TestCase):
    def test_rules_are_registered(self):
        self.assertGreaterEqual(len(REGISTRY[Scope.LIVE]), 20)
        self.assertGreaterEqual(len(REGISTRY[Scope.DAILY]), 15)

    def test_rule_ids_are_unique(self):
        ids = [spec.id for specs in REGISTRY.values() for spec in specs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_rule_declares_its_requirements(self):
        """A rule with no ``requires`` runs against every snapshot, including
        empty ones, and will KeyError the first time a signal is missing."""
        for spec in (s for specs in REGISTRY.values() for s in specs):
            with self.subTest(rule=spec.id):
                self.assertTrue(
                    spec.requires,
                    f"{spec.id} declares no required features",
                )

    def test_templates_only_reference_emitted_facts(self):
        """The templates and the predicate must agree.

        Checked by rendering with a deliberately empty fact set and asserting
        the failure is caught rather than raised — `render` returning None is
        the contract the engine relies on to drop a broken card instead of
        printing a literal "{run_text}" at the user.
        """
        for spec in (s for specs in REGISTRY.values() for s in specs):
            with self.subTest(rule=spec.id):
                result = render(spec, Finding(dedup_key="x", facts={}))
                self.assertIsNone(
                    result,
                    f"{spec.id} rendered with no facts — its templates take no "
                    f"substitutions, which is probably a mistake",
                )


class TestGating(unittest.TestCase):
    def test_missing_feature_gates_the_rule(self):
        spec = BY_ID["LV-01"]
        self.assertTrue(spec.gated(ctx()))

    def test_insufficient_history_gates_the_rule(self):
        spec = BY_ID["LV-01"]
        snapshot = ctx(
            days=2, active_run_min=200.0,
            **{"baseline.run_len.p90": 40.0, "baseline.run_len.n": 100},
        )
        self.assertTrue(spec.gated(snapshot))

    def test_satisfied_requirements_pass_the_gate(self):
        spec = BY_ID["LV-01"]
        snapshot = ctx(
            days=30, active_run_min=200.0, current_app="Code",
            **{"baseline.run_len.p90": 40.0, "baseline.run_len.n": 100},
        )
        self.assertFalse(spec.gated(snapshot))


class TestLiveRules(unittest.TestCase):
    def _run(self, rule_id: str, **features):
        spec = BY_ID[rule_id]
        snapshot = ctx(**features)
        if spec.gated(snapshot):
            return None
        return spec.fn(snapshot)

    def test_unbroken_stretch_fires_past_the_personal_bar(self):
        finding = self._run(
            "LV-01", active_run_min=120.0, current_app="Code",
            **{"baseline.run_len.p90": 40.0, "baseline.run_len.n": 100},
        )
        self.assertIsNotNone(finding)
        self.assertEqual(finding.dedup_key, "break/needed")
        self.assertIn("2h", finding.facts["run_text"])

    def test_unbroken_stretch_respects_the_75_minute_floor(self):
        """A near-miss: past the personal p90 but under the absolute floor."""
        finding = self._run(
            "LV-01", active_run_min=50.0, current_app="Code",
            **{"baseline.run_len.p90": 40.0, "baseline.run_len.n": 100},
        )
        self.assertIsNone(finding)

    def test_switch_storm_needs_a_rate_above_the_personal_p90(self):
        fires = self._run(
            "LV-03", switch_rate_15m=3.0,
            **{"baseline.switch_rate.p90": 2.1, "baseline.switch_rate.n": 500},
        )
        self.assertIsNotNone(fires)
        quiet = self._run(
            "LV-03", switch_rate_15m=0.2,
            **{"baseline.switch_rate.p90": 2.1, "baseline.switch_rate.n": 500},
        )
        self.assertIsNone(quiet)

    def test_distraction_run_requires_the_current_category_to_match(self):
        """A long run whose category is 'work' is not a distraction, however
        long it is — the run length alone must not be enough."""
        self.assertIsNone(
            self._run("LV-06", entertainment_run_min=60.0, current_category="work")
        )
        self.assertIsNotNone(
            self._run(
                "LV-06", entertainment_run_min=60.0,
                current_category="entertainment", current_app="vlc",
            )
        )

    def test_past_stop_time_uses_the_continuous_session_scale(self):
        """01:00 continuing last night's session is 25.0, not 1.0.

        On a raw clock it sorted below every daytime hour, so the rule needed a
        `now_hour >= 20` guard — which silenced it for exactly the small-hours
        sessions it most wanted to catch. A fresh 09:00 start must still not
        fire.
        """
        late = self._run(
            "LV-15", session_hour_now=25.0, session_run_min=300.0,
            **{"baseline.stop_hour.p90": 23.0, "baseline.stop_hour.n": 40},
        )
        self.assertIsNotNone(late)
        self.assertEqual(late.dedup_key, "load/late")

        morning = self._run(
            "LV-15", session_hour_now=9.0, session_run_min=60.0,
            **{"baseline.stop_hour.p90": 23.0, "baseline.stop_hour.n": 40},
        )
        self.assertIsNone(morning)

    def test_stop_hour_unwraps_past_midnight(self):
        """The whole reason the scale exists: a wrapped median is meaningless."""
        from app.services.recommendations.baselines import WorkSession
        evening = WorkSession(
            start=datetime(2026, 8, 14, 21, 0),
            end=datetime(2026, 8, 15, 1, 30),
        )
        self.assertAlmostEqual(evening.stop_hour, 25.5)
        self.assertAlmostEqual(evening.start_hour, 21.0)

    def test_clock_formatting_wraps_and_says_which_day(self):
        from app.services.recommendations.narrative import fmt_clock
        self.assertEqual(fmt_clock(16.85), "16:51")
        self.assertEqual(fmt_clock(25.5), "01:30 the next morning")


class TestEvidenceGate(unittest.TestCase):
    """No claim without n — the invariant the hardcoded page violated."""

    def test_engine_drops_a_finding_below_its_declared_min_n(self):
        engine = RecommendationEngine.__new__(RecommendationEngine)
        spec = BY_ID["LV-01"]
        self.assertGreater(spec.min_n, 0)
        weak = Finding(
            dedup_key="break/needed",
            facts={"run_text": "2h", "limit_text": "1h", "app": "Code"},
            evidence=Evidence(basis="personal_p90", n=spec.min_n - 1),
        )
        # _evaluate is where the gate lives; a stub spec returning the weak
        # finding must be filtered out rather than scored.
        stub = spec.__class__(**{**spec.__dict__, "fn": lambda _c: weak})
        out = RecommendationEngine._evaluate(engine, [stub], ctx(
            active_run_min=200.0, current_app="Code",
            **{"baseline.run_len.p90": 40.0, "baseline.run_len.n": 100},
        ))
        self.assertEqual(out, [])

    def test_absolute_evidence_is_fully_confident(self):
        self.assertEqual(Evidence(basis="absolute").confidence, 1.0)

    def test_confidence_grows_with_sample_size(self):
        self.assertLess(
            Evidence(basis="personal_p90", n=3).confidence,
            Evidence(basis="personal_p90", n=30).confidence,
        )


class TestBlocks(unittest.TestCase):
    def test_short_idle_does_not_end_a_block(self):
        """The OS marks idle after 120 s of no input, which anyone reading the
        screen trips constantly. Treating that as the end of a work block put
        the run-length p75 at eight minutes."""
        segments = [
            segment(0, 30),
            segment(30, 1, state="idle"),
            segment(31, 30),
        ]
        blocks = build_blocks(segments)
        self.assertEqual(len(blocks), 1)
        self.assertAlmostEqual(blocks[0].seconds / 60.0, 61.0, places=1)

    def test_long_absence_ends_a_block(self):
        segments = [segment(0, 30), segment(60, 30)]
        blocks = build_blocks(segments)
        self.assertEqual(len(blocks), 2)

    def test_bridge_boundary(self):
        gap_min = BLOCK_BRIDGE_SEC / 60.0
        joined = build_blocks([segment(0, 10), segment(10 + gap_min - 0.1, 10)])
        split = build_blocks([segment(0, 10), segment(10 + gap_min + 1, 10)])
        self.assertEqual(len(joined), 1)
        self.assertEqual(len(split), 2)


class TestStats(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertAlmostEqual(percentile([0.0, 10.0], 0.5), 5.0)

    def test_stat_needs_enough_samples_to_be_usable(self):
        self.assertFalse(Stat.of([1.0, 2.0]).usable)
        self.assertTrue(Stat.of([float(i) for i in range(20)]).usable)

    def test_unusable_baselines_are_not_flattened(self):
        """An unusable metric must be absent, not zero — absence is what the
        requirement gate reads to skip a rule instead of comparing against a
        fabricated threshold."""
        baselines = BaselineSet(global_stats={"focus": Stat.of([0.5, 0.6])})
        self.assertEqual(baselines.flatten(), {})

    def test_trough_within_band_excludes_the_small_hours(self):
        baselines = BaselineSet(
            hour_focus={2: 0.10, 13: 0.30, 9: 0.90},
            hour_samples={2: 50, 13: 50, 9: 50},
        )
        self.assertEqual(baselines.trough_hours(), [2, 13])
        self.assertEqual(baselines.trough_hours_within(8, 18), [13])


class TestNarrative(unittest.TestCase):
    def test_minute_formatting(self):
        self.assertEqual(fmt_minutes(0.4), "under a minute")
        self.assertEqual(fmt_minutes(45), "45m")
        self.assertEqual(fmt_minutes(60), "1h")
        self.assertEqual(fmt_minutes(95), "1h 35m")

    def test_magnitude_buckets_are_ordered(self):
        self.assertEqual(magnitude(0.5), "slightly")
        self.assertEqual(magnitude(1.5), "noticeably")
        self.assertEqual(magnitude(2.5), "clearly")
        self.assertEqual(magnitude(9.0), "sharply")

    def test_rendering_is_deterministic(self):
        spec = BY_ID["LV-01"]
        finding = Finding(
            dedup_key="break/needed",
            facts={"run_text": "2h", "limit_text": "1h", "app": "Code"},
        )
        self.assertEqual(render(spec, finding), render(spec, finding))


if __name__ == "__main__":
    unittest.main()


class TestPeriodMath(unittest.TestCase):
    """The statistics the weekly and monthly families rest on."""

    def test_theil_sen_is_robust_to_one_outlier(self):
        """The reason it is used instead of least squares.

        A four-week trend fitted through one exceptional week should still
        describe the other three. On [10, 20, 500, 40] the underlying slope is
        about 10 a week; least squares reports 57 because the outlier drags the
        line, while the median of pairwise slopes ignores it.
        """
        from app.services.recommendations.periods import theil_sen_slope
        self.assertAlmostEqual(theil_sen_slope([10.0, 20.0, 30.0, 40.0]), 10.0)

        spiked = [10.0, 20.0, 500.0, 40.0]
        robust = theil_sen_slope(spiked)
        self.assertAlmostEqual(robust, 10.0)

        # The least-squares slope on the same points, for contrast.
        xs = list(range(len(spiked)))
        mean_x = sum(xs) / len(xs)
        mean_y = sum(spiked) / len(spiked)
        least_squares = (
            sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, spiked))
            / sum((x - mean_x) ** 2 for x in xs)
        )
        self.assertGreater(least_squares, 50.0)
        self.assertLess(robust, least_squares / 5)

    def test_theil_sen_needs_three_points(self):
        from app.services.recommendations.periods import theil_sen_slope
        self.assertIsNone(theil_sen_slope([1.0, 2.0]))

    def test_spearman_detects_monotone_relationships(self):
        from app.services.recommendations.periods import spearman
        xs = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        self.assertAlmostEqual(spearman(xs, xs), 1.0)
        self.assertAlmostEqual(spearman(xs, list(reversed(xs))), -1.0)

    def test_spearman_refuses_a_short_series(self):
        from app.services.recommendations.periods import spearman
        self.assertIsNone(spearman([1.0, 2.0], [2.0, 1.0]))


class TestEffectGate(unittest.TestCase):
    """A matched effect must clear both arms or it does not exist."""

    def _effect(self, n_treated: int, n_control: int):
        from app.services.recommendations.effects import MatchedEffect
        return MatchedEffect(
            treated_median=0.4, control_median=0.7,
            n_treated=n_treated, n_control=n_control, relative=-0.43,
        )

    def test_thin_treatment_arm_is_not_credible(self):
        self.assertFalse(self._effect(3, 50).credible)

    def test_thin_control_arm_is_not_credible(self):
        self.assertFalse(self._effect(50, 3).credible)

    def test_both_arms_populated_is_credible(self):
        from app.services.recommendations.effects import MIN_ARM_SAMPLES
        self.assertTrue(self._effect(MIN_ARM_SAMPLES, MIN_ARM_SAMPLES).credible)


class TestRanker(unittest.TestCase):
    """Cold start must be a no-op, not a guess."""

    def test_untrained_ranker_is_neutral(self):
        from app.services.recommendations.ranker import RecommendationRanker
        fresh = RecommendationRanker.__new__(RecommendationRanker)
        fresh._model = None
        fresh._rule_index = {}
        import threading
        fresh._lock = threading.Lock()
        self.assertEqual(
            fresh.multiplier("LV-01", "high", "immediate", 9, 1, 0.8), 1.0
        )

    def test_cyclical_encoding_keeps_23_and_0_adjacent(self):
        from app.services.recommendations.ranker import _cyclical
        import math
        a, b = _cyclical(23, 24.0)
        c, d = _cyclical(0, 24.0)
        near = math.dist((a, b), (c, d))
        far = math.dist((a, b), _cyclical(11, 24.0))
        self.assertLess(near, far)


class TestReportNarrative(unittest.TestCase):
    """Reports must be reproducible — that is what template NLG buys."""

    def _facts(self):
        from app.services.report.facts import Metric, ReportFacts
        facts = ReportFacts(
            scope="daily",
            period_label="Friday, 14 August 2026",
            period_start="2026-08-14",
            period_end="2026-08-14",
            generated_at="2026-08-14T23:00:00",
            days_of_history=29,
        )
        facts.metrics = [
            Metric("active", "Active time", 235.0, "min", 167.0, 68.0),
            Metric("deep", "Deep work", 65.0, "min", 29.0, 36.0),
        ]
        return facts

    def test_rendering_is_byte_identical_across_runs(self):
        from app.services.report.narrative import build_sections, render_markdown
        facts = self._facts()
        first = render_markdown(facts, build_sections(facts))
        second = render_markdown(facts, build_sections(facts))
        self.assertEqual(first, second)

    def test_no_baseline_means_no_comparison_clause(self):
        """A missing baseline had fewer than eight samples behind it. Inventing
        a comparison there is the failure the whole engine guards against."""
        from app.services.report.facts import Metric
        from app.services.report.narrative import _comparison_clause
        self.assertEqual(
            _comparison_clause(Metric("x", "X", 100.0, "min", None, None)), ""
        )
        self.assertIn(
            "above", _comparison_clause(Metric("x", "X", 100.0, "min", 50.0, 50.0))
        )

    def test_empty_period_says_so_rather_than_inventing_a_report(self):
        from app.services.report.narrative import build_sections
        facts = self._facts()
        facts.has_activity = False
        sections = build_sections(facts)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].key, "empty")

    def test_quality_section_is_always_present(self):
        from app.services.report.narrative import build_sections
        keys = [s.key for s in build_sections(self._facts())]
        self.assertIn("quality", keys)
