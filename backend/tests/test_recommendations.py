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
from app.services.recommendations.narrative import (
    fmt_clock,
    fmt_hour,
    fmt_minutes,
    magnitude,
    render,
)
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

    def test_clock_rounds_before_it_wraps(self):
        """The minute carry must not cross midnight behind the day count's back.

        Rounding after the modulo produced "23:60" from fmt_hour and, worse,
        "00:00" with no day qualifier from fmt_clock — a stop-time percentile a
        thousandth of an hour short of midnight reported as the previous
        morning.
        """
        self.assertEqual(fmt_hour(23.999), "00:00")
        self.assertEqual(fmt_clock(23.999), "00:00 the next morning")

    def test_hour_is_always_a_valid_clock_time(self):
        for step in range(0, 48 * 60):
            value = step / 60.0
            with self.subTest(value=value):
                hour, _, minute = fmt_hour(value).partition(":")
                self.assertLess(int(hour), 24)
                self.assertLess(int(minute), 60)

    def test_clock_qualifies_the_day_it_lands_on(self):
        self.assertEqual(fmt_clock(18.82), "18:49")
        self.assertEqual(fmt_clock(25.5), "01:30 the next morning")
        # One day over but not morning — "the next morning" would be wrong.
        self.assertEqual(fmt_clock(47.99), "23:59 the next day")

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


class TestRecoverySpans(unittest.TestCase):
    """The bisect membership test must agree with the scan it replaced."""

    def _spans(self, *pairs):
        return [
            (BASE + timedelta(minutes=a), BASE + timedelta(minutes=b))
            for a, b in pairs
        ]

    def test_overlapping_spans_are_coalesced(self):
        from app.services.recommendations.effects import _merge_spans
        merged = _merge_spans(self._spans((0, 60), (30, 90), (200, 260)))
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0][1], BASE + timedelta(minutes=90))

    def test_adjacent_spans_are_coalesced(self):
        from app.services.recommendations.effects import _merge_spans
        merged = _merge_spans(self._spans((0, 60), (60, 120)))
        self.assertEqual(len(merged), 1)

    def test_unsorted_input_is_handled(self):
        from app.services.recommendations.effects import _merge_spans
        merged = _merge_spans(self._spans((200, 260), (0, 60)))
        self.assertEqual(merged[0][0], BASE)

    def test_membership_matches_the_linear_scan(self):
        """The property that matters: same answer as `any(start <= w < stop)`.

        Checked over a grid that straddles every boundary, because the failure
        this replaces would be an off-by-one at a span edge silently moving a
        window from the treated arm to the control arm.
        """
        from bisect import bisect_right
        from app.services.recommendations.effects import _merge_spans

        spans = self._spans((0, 60), (30, 90), (200, 260), (255, 300))
        merged = _merge_spans(spans)
        starts = [s for s, _ in merged]

        for minute in range(-10, 330):
            when = BASE + timedelta(minutes=minute)
            expected = any(start <= when < stop for start, stop in spans)
            index = bisect_right(starts, when) - 1
            actual = index >= 0 and when < merged[index][1]
            with self.subTest(minute=minute):
                self.assertEqual(actual, expected)


class TestPersistence(unittest.TestCase):
    """The batched write must keep the per-row isolation it replaced."""

    def setUp(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import RecommendationEventRecord, RecommendationRecord

        self.db_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            bind=self.db_engine,
            tables=[
                RecommendationRecord.__table__,
                RecommendationEventRecord.__table__,
            ],
        )
        self.Session = sessionmaker(bind=self.db_engine)
        self.db = self.Session()
        self.engine = RecommendationEngine.__new__(RecommendationEngine)
        self.Record = RecommendationRecord

    def tearDown(self):
        self.db.close()
        self.db_engine.dispose()

    def _spec(self, rule_id="TS-01", cooldown=timedelta(hours=6)):
        from app.services.recommendations.types import RuleSpec, Section, Severity
        return RuleSpec(
            id=rule_id, version=1, scope=Scope.DAILY, section=Section.INSIGHT,
            severity=Severity.LOW,
            title="Title {v}", why="Why {v}", action="Do {v}",
            fn=lambda c: None, cooldown=cooldown,
        )

    def _record(self, dedup_key, rule_id="TS-01"):
        finding = Finding(
            dedup_key=dedup_key,
            facts={"v": dedup_key},
            evidence=Evidence(basis="absolute"),
        )
        return self.engine._build(self._spec(rule_id), finding, 1.0, ctx(), BASE)

    def _write(self, *dedup_keys):
        return self.engine._write(
            self.db, [self._record(key) for key in dedup_keys]
        )

    def _count(self):
        return self.db.query(self.Record).count()

    def test_a_scope_commits_once_for_the_whole_batch(self):
        """The measured win: one fsync per scope, not one per card.

        pysqlite runs in legacy mode and implicitly commits before any non-DML
        statement, so a SAVEPOINT per row would quietly restore the old
        behaviour. Counting COMMITs is the only way to notice that regression.
        """
        from sqlalchemy import event

        commits = []

        def on_commit(_conn):
            commits.append(1)

        event.listen(self.db_engine, "commit", on_commit)
        try:
            self.assertEqual(self._write("a", "b", "c", "d", "e"), 5)
        finally:
            event.remove(self.db_engine, "commit", on_commit)
        self.assertEqual(self._count(), 5)
        self.assertEqual(len(commits), 1)

    def test_a_racing_duplicate_does_not_lose_the_batch(self):
        """The concurrent-writer case the unique index exists for.

        The pre-check in `_run_scope` makes this rare, not impossible: the live
        job and an on-demand API call can render the same card in the same
        instant. When the batch insert loses that race, the rows beside the
        duplicate must still land.
        """
        self.assertEqual(self._write("b"), 1)
        # "b" already exists, so this batch violates the unique index.
        self.assertEqual(self._write("d", "b", "e"), 2)
        keys = {row.dedup_key for row in self.db.query(self.Record).all()}
        self.assertEqual(keys, {"b", "d", "e"})

    def test_the_session_survives_a_rejected_batch(self):
        self._write("x")
        self._write("x", "y")
        self.assertEqual(self._write("z"), 1)
        self.assertEqual(self._count(), 3)

    def test_an_empty_batch_touches_nothing(self):
        self.assertEqual(self.engine._write(self.db, []), 0)
        self.assertEqual(self._count(), 0)

    def test_existing_keys_are_read_for_the_day(self):
        self._write("a", "b")
        keys = self.engine._existing_keys(self.db, "test_user", "2026-08-14")
        self.assertEqual(keys, {"a", "b"})
        self.assertEqual(
            self.engine._existing_keys(self.db, "test_user", "2026-08-15"), set()
        )

    def test_a_rule_whose_template_cannot_render_produces_no_row(self):
        """A missing fact is a rule bug, and must not reach the database."""
        broken = Finding(dedup_key="k", facts={}, evidence=Evidence(basis="absolute"))
        self.assertIsNone(
            self.engine._build(self._spec(), broken, 1.0, ctx(), BASE)
        )


class TestCooldown(TestPersistence):
    """One grouped read must reproduce the per-rule query's verdicts."""

    def _write_as(self, dedup_key: str, rule_id: str) -> None:
        self.engine._write(self.db, [self._record(dedup_key, rule_id)])

    def test_a_rule_inside_its_cooldown_is_suppressed(self):
        self._write_as("k", "TS-01")
        spec = self._spec("TS-01", cooldown=timedelta(hours=6))
        last = self.engine._last_fired(self.db, "test_user", [spec], BASE)
        self.assertTrue(self.engine._on_cooldown(last, spec, BASE))

    def test_a_rule_past_its_cooldown_is_allowed(self):
        self._write_as("k", "TS-01")
        spec = self._spec("TS-01", cooldown=timedelta(hours=6))
        later = BASE + timedelta(hours=7)
        last = self.engine._last_fired(self.db, "test_user", [spec], later)
        self.assertFalse(self.engine._on_cooldown(last, spec, later))

    def test_an_unfired_rule_is_never_on_cooldown(self):
        spec = self._spec("TS-99")
        last = self.engine._last_fired(self.db, "test_user", [spec], BASE)
        self.assertFalse(self.engine._on_cooldown(last, spec, BASE))

    def test_the_horizon_covers_the_longest_cooldown_in_the_family(self):
        """A short-cooldown rule must not shrink the window a long one needs."""
        self._write_as("k", "TS-LONG")
        brief = self._spec("TS-BRIEF", cooldown=timedelta(minutes=5))
        lengthy = self._spec("TS-LONG", cooldown=timedelta(days=7))
        as_of = BASE + timedelta(days=3)
        last = self.engine._last_fired(self.db, "test_user", [brief, lengthy], as_of)
        self.assertIn("TS-LONG", last)
        self.assertTrue(self.engine._on_cooldown(last, lengthy, as_of))

    def test_one_query_serves_the_whole_family(self):
        """Twenty rules, one read. This is the whole point of the change."""
        from sqlalchemy import event

        specs = [self._spec(f"TS-{i:02d}") for i in range(20)]
        seen = []

        def count(*_args):
            seen.append(1)

        event.listen(self.db_engine, "before_cursor_execute", count)
        try:
            self.engine._last_fired(self.db, "test_user", specs, BASE)
        finally:
            event.remove(self.db_engine, "before_cursor_execute", count)
        self.assertEqual(len(seen), 1)


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
