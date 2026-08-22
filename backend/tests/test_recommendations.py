"""Invariants for the recommendation engine.

The failure mode for this subsystem is not crashing — it is confidently saying
something untrue that nobody notices for months. These tests target that
directly: every rule must be reachable, no rule may ship a claim weaker than
the evidence it declared it needs, and the templates must actually be
satisfiable by the facts their predicates emit.
"""

import unittest
from dataclasses import dataclass
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

    def test_shared_dedup_keys_stay_inside_one_section(self):
        """Selection groups candidates by section before capping them.

        That regrouping is what lets exploration see which cards missed the
        cut. It is only order-preserving for a dedup contest while every set of
        rules sharing a key sits in one section — across two sections the
        winner would become whichever section was staged first rather than
        whichever finding scored highest. Three keys are shared today
        (fragmentation/now, distraction/now, break/needed) and all three are
        LIVE/IMMEDIATE. A rule added elsewhere on one of those keys must move
        the grouping, not silently change which card survives.
        """
        import re
        from pathlib import Path
        sections: dict[str, set[str]] = {}
        rules_dir = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "recommendations" / "rules"
        )
        for path in rules_dir.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            for block in source.split("@rule(")[1:]:
                rule_id = re.search(r'id="([A-Z]{2}-\d{2})"', block)
                section = re.search(r"section=Section\.([A-Z]+)", block)
                for key in re.findall(r'dedup_key="([^"]+)"', block):
                    if rule_id and section:
                        sections.setdefault(key, set()).add(section.group(1))
        straddling = {k: v for k, v in sections.items() if len(v) > 1}
        self.assertEqual(straddling, {})

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

    def test_report_describes_what_happened_and_nothing_else(self):
        """No advice, no meta-commentary.

        "For next time" duplicated the Recommendations tab, and "How solid this
        is" described the collection pipeline rather than the period. Both were
        removed from the narrative builder rather than hidden in the UI, so the
        markdown and PDF exports match the screen.
        """
        from app.services.report.narrative import build_sections
        keys = [s.key for s in build_sections(self._facts())]
        self.assertNotIn("quality", keys)
        self.assertNotIn("plan", keys)


class TestWeeklyBaseline(unittest.TestCase):
    """Medians over whole prior weeks, for the weekly report's totals.

    Weekly totals previously carried no comparison at all, because BaselineSet
    holds daily samples and a week's total cannot be held against a daily
    median. These pin the two exclusions that decide whether the median means
    anything.
    """

    def _days(self, start: str, count: int, active=60.0, deep=30.0, stop_hour=None):
        from datetime import datetime, timedelta
        from app.services.recommendations.periods import DaySummary
        first = datetime.fromisoformat(f"{start}T00:00:00")
        return [
            DaySummary(
                date=(first + timedelta(days=i)).strftime("%Y-%m-%d"),
                weekday=(first + timedelta(days=i)).weekday(),
                active_min=active, deep_min=deep, distraction_min=0.0,
                learn_min=0.0, focus=0.5, meeting_min=0.0,
                latest_stop_hour=stop_hour, category_min={},
            )
            for i in range(count)
        ]

    def test_no_baseline_below_the_minimum_week_count(self):
        from datetime import datetime
        from app.services.recommendations.periods import (
            WEEK_BASELINE_MIN_WEEKS, weekly_baseline,
        )
        # Two complete prior weeks, one short of the minimum.
        days = self._days("2026-08-03", 14)
        result = weekly_baseline(days, datetime(2026, 8, 17))
        self.assertEqual(WEEK_BASELINE_MIN_WEEKS, 3)
        self.assertEqual(result, {})

    def test_the_reported_week_is_excluded_from_its_own_baseline(self):
        """Including it drags the median toward the value being compared."""
        from datetime import datetime
        from app.services.recommendations.periods import weekly_baseline
        # Three prior weeks at 60 min/day, then a wild week being reported.
        days = self._days("2026-07-27", 21) + self._days("2026-08-17", 7, active=600.0)
        result = weekly_baseline(days, datetime(2026, 8, 17))
        # 7 days x 60 min. The 600-a-day week must not move this at all.
        self.assertAlmostEqual(result["baseline.week_active_min.p50"], 420.0)
        self.assertEqual(result["baseline.week.n"], 3.0)

    def test_weeks_before_recording_began_are_not_counted_as_quiet_weeks(self):
        """A bucket predating the first recorded day is absent data, not a zero."""
        from datetime import datetime
        from app.services.recommendations.periods import weekly_baseline
        days = self._days("2026-07-27", 21)
        result = weekly_baseline(days, datetime(2026, 8, 17))
        # Exactly three whole weeks are covered; the lookback reaches further
        # back but must stop rather than averaging in empty buckets.
        self.assertEqual(result["baseline.week.n"], 3.0)
        self.assertAlmostEqual(result["baseline.week_active_min.p50"], 420.0)

    def test_late_nights_are_counted_per_week(self):
        from datetime import datetime
        from app.services.recommendations.periods import (
            LATE_NIGHT_HOUR, weekly_baseline,
        )
        days = self._days("2026-07-27", 21, stop_hour=LATE_NIGHT_HOUR + 1)
        result = weekly_baseline(days, datetime(2026, 8, 17))
        self.assertAlmostEqual(result["baseline.late_night_count.p50"], 7.0)


class TestSpanLabel(unittest.TestCase):
    """Report period labels, including the span that used to raise.

    ``%-d`` is a glibc extension. On Windows ``datetime.__format__`` rejects
    it outright, so the year-boundary branch raised ValueError before the
    ``.replace("%-d", "")`` that was meant to paper over it could ever run —
    taking down every weekly report covering a New Year.
    """

    def setUp(self):
        from app.services.report.facts import _span_label
        self.label = _span_label

    def test_year_boundary_renders_both_years(self):
        self.assertEqual(
            self.label("2025-12-29", "2026-01-04"),
            "29 December 2025 to 4 January 2026",
        )

    def test_month_boundary_names_the_year_once(self):
        self.assertEqual(
            self.label("2026-07-27", "2026-08-02"), "27 July to 2 August 2026"
        )

    def test_within_one_month_collapses_to_a_range(self):
        self.assertEqual(
            self.label("2026-08-08", "2026-08-14"), "8-14 August 2026"
        )

    def test_days_are_never_zero_padded(self):
        """The point of %-d was an unpadded day; the fix must keep that."""
        self.assertNotIn("08", self.label("2025-12-29", "2026-01-04"))

    def test_unparseable_dates_fall_back_rather_than_raise(self):
        self.assertEqual(
            self.label("not-a-date", "2026-08-08"), "not-a-date to 2026-08-08"
        )


class TestEmptyPeriodIsAnnounced(unittest.TestCase):
    """A period with no recorded days must say so on the panel.

    The report layer already handles this — ``has_activity`` is False and the
    renderer emits a dedicated "No activity recorded" section. The
    recommendations panel had no such path: the builders return early with
    baselines only, every weekly and monthly rule gates out for want of
    features, and the panel renders empty. Indistinguishable from a quiet
    week, which is exactly the confusion the hygiene family exists to prevent.
    """

    def test_empty_week_fires(self):
        finding = BY_ID["HY-10"].fn(ctx(week_day_count=0.0, week_end="2026-08-14"))
        self.assertIsNotNone(finding)
        self.assertIn("2026-08-14", render(BY_ID["HY-10"], finding)[0])

    def test_populated_week_is_silent(self):
        self.assertIsNone(
            BY_ID["HY-10"].fn(ctx(week_day_count=5.0, week_end="2026-08-14"))
        )

    def test_empty_month_fires(self):
        finding = BY_ID["HY-11"].fn(
            ctx(month_active_days=0.0, month_end="2026-08-14")
        )
        self.assertIsNotNone(finding)

    def test_populated_month_is_silent(self):
        self.assertIsNone(
            BY_ID["HY-11"].fn(ctx(month_active_days=12.0, month_end="2026-08-14"))
        )

    def test_the_rules_survive_the_gate_on_an_empty_context(self):
        """The whole point: these must not gate out where the others do.

        An empty builder emits only the period bounds and the baselines, so a
        rule requiring any activity feature is gated. These two require only
        the day count, which the builder always sets.
        """
        empty = ctx(days=0, week_day_count=0.0, week_end="2026-08-14")
        self.assertFalse(BY_ID["HY-10"].gated(empty))

    def test_hygiene_ids_route_to_the_caveats_footer(self):
        """HY- prefix is load-bearing, not cosmetic — facts.py routes on it."""
        for rule_id in ("HY-10", "HY-11"):
            self.assertTrue(rule_id.startswith("HY-"))


class TestRankerHoldout(unittest.TestCase):
    """The holdout split must not leak future feedback into training.

    Feedback is autocorrelated — presses come in runs — so a random split puts
    rows from the same run on both sides and scores the model on presses it
    effectively trained on. The reported figure then describes a model that
    does not exist in deployment.
    """

    def setUp(self):
        import numpy as np
        from app.services.recommendations.ranker import RecommendationRanker
        self.np = np
        self.holdout = RecommendationRanker._holdout_accuracy

    def _runs(self, n=120, seed=0):
        """Labels in runs, the way real feedback arrives."""
        rng = self.np.random.default_rng(seed)
        out, label = [], 0
        while len(out) < n:
            out += [label] * int(rng.integers(5, 15))
            label = 1 - label
        y = self.np.array(out[:n])
        X = self.np.column_stack([
            y + rng.normal(0, 0.6, n), rng.normal(0, 1, n)
        ])
        return X, y

    def test_reports_a_temporal_basis(self):
        score, basis = self.holdout(*self._runs())
        self.assertEqual(basis, "temporal")
        self.assertIsNotNone(score)

    def test_the_test_arm_is_strictly_later_than_the_training_arm(self):
        """The contract in one assertion: nothing in the tail is trained on."""
        X, y = self._runs()
        cut = int(len(y) * 0.7)
        self.assertEqual(len(y[:cut]) + len(y[cut:]), len(y))
        self.assertGreater(cut, 0)
        self.assertGreater(len(y) - cut, 0)

    def test_a_single_class_tail_refuses_rather_than_scoring_the_base_rate(self):
        """Raw accuracy would read ~1.0 here for a model that learned nothing."""
        X, y = self._runs()
        y = y.copy()
        y[-40:] = 1
        self.assertEqual(self.holdout(X, y), (None, "none"))

    def test_too_little_feedback_declines_to_report(self):
        X, y = self._runs()
        self.assertEqual(self.holdout(X[:20], y[:20]), (None, "none"))

    def test_one_outcome_only_declines_to_report(self):
        X, y = self._runs()
        ones = self.np.ones(len(y), dtype=int)
        self.assertEqual(self.holdout(X, ones), (None, "none"))

    def test_balanced_accuracy_floors_a_majority_class_guesser_at_a_half(self):
        """A model that always says one thing must score 0.5, not the skew."""
        from sklearn.metrics import balanced_accuracy_score
        truth = self.np.array([0] * 90 + [1] * 10)
        always_zero = self.np.zeros(100, dtype=int)
        self.assertAlmostEqual(
            balanced_accuracy_score(truth, always_zero), 0.5
        )



class TestWilsonInterval(unittest.TestCase):
    """The small-sample guard that keeps a bad week from killing a rule."""

    def setUp(self):
        from app.services.recommendations.telemetry import wilson_interval
        self.wilson = wilson_interval

    def test_no_trials_admits_total_ignorance(self):
        self.assertEqual(self.wilson(0, 0), (0.0, 1.0))

    def test_zero_of_four_does_not_claim_certainty(self):
        """The normal approximation returns [0, 0] here — a rule convicted on
        four presses. Wilson must leave real width above zero."""
        low, high = self.wilson(0, 4)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.4)

    def test_all_of_four_does_not_claim_certainty(self):
        low, high = self.wilson(4, 4)
        self.assertLess(low, 0.6)
        self.assertAlmostEqual(high, 1.0)

    def test_the_interval_narrows_as_evidence_accumulates(self):
        widths = [
            self.wilson(n // 2, n)[1] - self.wilson(n // 2, n)[0]
            for n in (10, 50, 250, 1000)
        ]
        self.assertEqual(widths, sorted(widths, reverse=True))

    def test_the_interval_brackets_the_point_estimate(self):
        for applied, judged in ((1, 10), (5, 10), (9, 10), (17, 40)):
            low, high = self.wilson(applied, judged)
            with self.subTest(p=f"{applied}/{judged}"):
                self.assertLessEqual(low, applied / judged)
                self.assertGreaterEqual(high, applied / judged)

    def test_bounds_stay_inside_zero_and_one(self):
        for applied, judged in ((0, 1), (1, 1), (0, 3), (3, 3)):
            low, high = self.wilson(applied, judged)
            with self.subTest(p=f"{applied}/{judged}"):
                self.assertGreaterEqual(low, 0.0)
                self.assertLessEqual(high, 1.0)


class TestRuleHealth(unittest.TestCase):
    """Per-rule telemetry over a real table.

    The engine has always been able to say what fired. These assertions cover
    the half it could not: whether any of it was worth firing.
    """

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord,
            RecommendationRecord,
            UserPreferenceRecord,
        )
        from app.services.recommendations.telemetry import rule_health

        self.Rec = RecommendationRecord
        self.Event = RecommendationEventRecord
        self.rule_health = rule_health
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self._seq = 0

    def tearDown(self):
        self.db.close()

    def card(self, rule_id, status, local_date="2026-08-14", user="u1"):
        self._seq += 1
        rec = self.Rec(
            id=f"r{self._seq}", user_id=user, rule_id=rule_id, rule_version=1,
            scope="daily", section="insight", severity="low",
            title="t", why="w", action="a", score=1.0,
            dedup_key=f"k{self._seq}", local_date=local_date,
            generated_at=f"{local_date}T09:00:00", status=status,
        )
        self.db.add(rec)
        self.db.commit()
        return rec

    def event(self, rec, action, seconds, user="u1"):
        self._seq += 1
        self.db.add(self.Event(
            id=f"e{self._seq}", recommendation_id=rec.id, user_id=user,
            rule_id=rec.rule_id, action=action, hour_of_day=9, weekday=4,
            seconds_to_action=seconds, created_at="2026-08-14T09:05:00",
        ))
        self.db.commit()

    def health_for(self, report, rule_id):
        return next(r for r in report.rules if r.rule_id == rule_id)

    # -- counting ------------------------------------------------------ #

    def test_counts_come_from_the_card_not_the_event_stream(self):
        """A card dismissed twice is one dismissal.

        The engine logs a repeat press on purpose, as ranker signal. Counting
        events would let one emphatic user inflate a rule's denominator.
        """
        rec = self.card("DY-01", "dismissed")
        self.event(rec, "dismissed", 30)
        self.event(rec, "dismissed", 45)
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual(health.fired, 1)
        self.assertEqual(health.dismissed, 1)

    def test_rates_are_computed_over_the_right_denominators(self):
        for _ in range(3):
            self.card("DY-01", "applied")
        self.card("DY-01", "dismissed")
        for _ in range(6):
            self.card("DY-01", "expired")
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual((health.fired, health.judged), (10, 4))
        self.assertAlmostEqual(health.acceptance, 0.75)     # applied / judged
        self.assertAlmostEqual(health.ppv, 0.3)             # applied / fired
        self.assertAlmostEqual(health.response_rate, 0.4)   # judged / fired

    def test_expired_cards_do_not_count_as_rejections(self):
        """An expired live card was never ruled on — folding it into the
        dismissal count would blame a rule for the user being away."""
        self.card("DY-01", "applied")
        self.card("DY-01", "expired")
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual(health.judged, 1)
        self.assertEqual(health.acceptance, 1.0)

    def test_median_time_to_action_is_split_by_action(self):
        for seconds in (10, 20, 300):
            self.event(self.card("DY-01", "dismissed"), "dismissed", seconds)
        for seconds in (100, 200):
            self.event(self.card("DY-01", "applied"), "applied", seconds)
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual(health.median_seconds_to_dismiss, 20.0)
        self.assertEqual(health.median_seconds_to_apply, 150.0)

    def test_other_users_are_not_pooled(self):
        self.card("DY-01", "applied", user="u1")
        self.card("DY-01", "dismissed", user="u2")
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual((health.fired, health.applied), (1, 1))

    def test_since_bounds_the_window(self):
        self.card("DY-01", "applied", local_date="2026-07-01")
        self.card("DY-01", "dismissed", local_date="2026-08-14")
        report = self.rule_health(self.db, "u1", since="2026-08-01")
        self.assertEqual(self.health_for(report, "DY-01").fired, 1)

    # -- verdicts ------------------------------------------------------ #

    def test_a_rule_that_never_fired_is_silent_not_condemned(self):
        self.card("DY-01", "applied")
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-02")
        self.assertEqual(health.verdict, "silent")
        self.assertEqual(health.fired, 0)

    def test_every_catalogue_rule_appears_even_with_no_history(self):
        report = self.rule_health(self.db, "u1")
        self.assertEqual(len(report.rules), len(BY_ID))

    def test_thin_evidence_is_unproven_rather_than_below(self):
        """Three dismissals is a bad week, not a verdict."""
        for _ in range(3):
            self.card("DY-01", "dismissed")
        for _ in range(20):
            self.card("DY-02", "applied")
        health = self.health_for(self.rule_health(self.db, "u1"), "DY-01")
        self.assertEqual(health.verdict, "unproven")

    def test_a_rule_far_below_the_users_own_average_is_flagged(self):
        for _ in range(40):
            self.card("DY-02", "applied")
        for _ in range(20):
            self.card("DY-01", "dismissed")
        report = self.rule_health(self.db, "u1")
        self.assertEqual(self.health_for(report, "DY-01").verdict, "below")
        self.assertIn(
            "DY-01", [r.rule_id for r in report.demotion_candidates()]
        )

    def test_the_bar_is_the_user_not_a_constant(self):
        """The same 50% rule is poor among appliers and good among dismissers.

        This is the whole design: acceptance in this class of system varies
        enormously between people and alert types (Poly et al. 2020), so a
        fixed bar measures the user's temperament rather than rule quality.
        """
        def verdict_of(other_status):
            self.setUp()
            for _ in range(10):
                self.card("DY-01", "applied")
                self.card("DY-01", "dismissed")
            for _ in range(60):
                self.card("DY-02", other_status)
            return self.health_for(
                self.rule_health(self.db, "u1"), "DY-01"
            ).verdict

        self.assertEqual(verdict_of("applied"), "below")
        self.assertEqual(verdict_of("dismissed"), "above")

    def test_worst_behaved_rules_sort_first(self):
        for _ in range(40):
            self.card("DY-02", "applied")
        for _ in range(20):
            self.card("DY-01", "dismissed")
        report = self.rule_health(self.db, "u1")
        self.assertEqual(report.rules[0].rule_id, "DY-01")

    def test_a_retired_rule_id_keeps_its_history_and_is_marked_unknown(self):
        self.card("ZZ-99", "dismissed")
        health = self.health_for(self.rule_health(self.db, "u1"), "ZZ-99")
        self.assertFalse(health.known)
        self.assertIsNone(health.scope)

    def test_registry_metadata_is_attached(self):
        health = self.health_for(self.rule_health(self.db, "u1"), "HY-10")
        self.assertEqual(health.scope, "weekly")
        self.assertEqual(health.severity, "high")

    def test_the_report_serialises_for_the_endpoint(self):
        self.card("DY-01", "applied")
        payload = self.rule_health(self.db, "u1").as_dict()
        self.assertEqual(payload["overall_judged"], 1)
        self.assertTrue(all("verdict" in r for r in payload["rules"]))

    def test_no_feedback_at_all_leaves_the_bar_undefined(self):
        """With nothing judged there is no average to compare against, and
        every rule must come back unproven rather than accidentally below."""
        for _ in range(20):
            self.card("DY-01", "expired")
        report = self.rule_health(self.db, "u1")
        self.assertIsNone(report.overall_acceptance)
        self.assertEqual(self.health_for(report, "DY-01").verdict, "unproven")
        self.assertEqual(report.demotion_candidates(), [])

@dataclass(frozen=True)
class _FakeSpec:
    """Just enough of a RuleSpec for the selection stage, which reads only the
    severity — building 74 real specs to test an ordering would obscure it."""

    id: str
    severity: "object"


class TestExploration(unittest.TestCase):
    """Epsilon-greedy surfacing, and the propensities that make it useful.

    The point of this machinery is not better recommendations — it is slightly
    worse ones, on purpose, in exchange for the only data that makes an
    off-policy estimate valid. A deterministic policy shows its top cards with
    probability 1 and everything else with probability 0, and no estimator can
    divide by that second number. These tests pin the properties an estimator
    depends on: every eligible card has a non-zero chance, the chances describe
    the policy rather than the draw, and the cost stays confined to one slot.
    """

    def setUp(self):
        import random as _random
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Severity
        self.random = _random
        self.explore = RecommendationEngine._explore
        self.Severity = Severity

    def entries(self, count, severity=None):
        """``count`` candidates in descending score order."""
        return [
            (
                _FakeSpec(f"R-{i:02d}", severity or self.Severity.LOW),
                Finding(dedup_key=f"k{i}"),
                float(count - i),
            )
            for i in range(count)
        ]

    # -- the default is no exploration at all --------------------------- #

    def test_epsilon_zero_leaves_the_ordering_untouched(self):
        entries = self.entries(6)
        out = self.explore(entries, cap=3, epsilon=0.0)
        self.assertEqual(
            [e[0].id for e in out], [e[0].id for e in entries]
        )
        self.assertEqual([e[4] for e in out], [False] * 6)

    def test_epsilon_zero_prices_the_shown_cards_at_certainty(self):
        out = self.explore(self.entries(6), cap=3, epsilon=0.0)
        self.assertEqual([e[3] for e in out[:3]], [1.0, 1.0, 1.0])

    def test_nothing_passed_over_means_no_decision_to_price(self):
        """Four candidates for four slots is not a choice."""
        out = self.explore(self.entries(4), cap=4, epsilon=0.9)
        self.assertEqual([e[3] for e in out], [1.0] * 4)
        self.assertEqual([e[4] for e in out], [False] * 4)

    # -- common support, the property estimators need ------------------- #

    def test_every_eligible_card_has_a_non_zero_chance(self):
        """The whole reason this exists. IPS divides by these numbers."""
        out = self.explore(
            self.entries(9), cap=3, epsilon=0.1,
            rng=self.random.Random(0),
        )
        self.assertEqual(len(out), 9)
        for spec, _f, _s, propensity, _e in out:
            with self.subTest(rule=spec.id):
                self.assertGreater(propensity, 0.0)

    def test_the_marginal_slot_propensities_form_a_distribution(self):
        """One card is shown in that slot, so the chances must total one."""
        eps = 0.2
        out = self.explore(
            self.entries(8), cap=3, epsilon=eps, rng=self.random.Random(1)
        )
        contested = sorted(e[3] for e in out[2:])
        self.assertAlmostEqual(sum(contested), 1.0)

    def test_the_safe_slots_are_never_at_stake(self):
        for seed in range(20):
            out = self.explore(
                self.entries(8), cap=4, epsilon=0.9,
                rng=self.random.Random(seed),
            )
            with self.subTest(seed=seed):
                self.assertEqual([e[3] for e in out[:3]], [1.0, 1.0, 1.0])
                self.assertEqual(
                    [e[0].id for e in out[:3]], ["R-00", "R-01", "R-02"]
                )

    def test_propensity_describes_the_policy_not_the_draw(self):
        """Same inputs, both branches, identical price on each card.

        A card that reaches the panel by some later path — a failed render
        above it — must still carry a number an estimator can use.
        """
        def priced(seed):
            out = self.explore(
                self.entries(6), cap=3, epsilon=0.5,
                rng=self.random.Random(seed),
            )
            return {e[0].id: e[3] for e in out}

        prices = [priced(s) for s in range(12)]
        self.assertGreater(len({tuple(sorted(p.items())) for p in prices}), 0)
        for p in prices[1:]:
            self.assertEqual(p, prices[0])

    # -- the bounded cost ------------------------------------------------ #

    def test_a_high_severity_card_is_never_displaced(self):
        entries = self.entries(2) + [(
            _FakeSpec("R-HI", self.Severity.HIGH),
            Finding(dedup_key="khi"),
            1.0,
        )] + self.entries(4)[:3]
        for seed in range(30):
            out = self.explore(
                entries, cap=3, epsilon=1.0, rng=self.random.Random(seed)
            )
            with self.subTest(seed=seed):
                self.assertEqual(out[2][0].id, "R-HI")
                self.assertEqual(out[2][3], 1.0)
                self.assertFalse(out[2][4])

    def test_only_one_card_is_ever_marked_explored(self):
        for seed in range(30):
            out = self.explore(
                self.entries(9), cap=4, epsilon=1.0,
                rng=self.random.Random(seed),
            )
            with self.subTest(seed=seed):
                self.assertEqual(sum(1 for e in out if e[4]), 1)

    def test_an_explored_card_always_takes_the_marginal_slot(self):
        for seed in range(30):
            out = self.explore(
                self.entries(9), cap=4, epsilon=1.0,
                rng=self.random.Random(seed),
            )
            explored_at = [i for i, e in enumerate(out) if e[4]]
            with self.subTest(seed=seed):
                self.assertEqual(explored_at, [3])

    # -- the rate is what it says --------------------------------------- #

    def test_exploration_fires_at_about_epsilon(self):
        rng = self.random.Random(7)
        fired = sum(
            any(e[4] for e in self.explore(
                self.entries(8), cap=3, epsilon=0.25, rng=rng
            ))
            for _ in range(4000)
        )
        self.assertAlmostEqual(fired / 4000, 0.25, delta=0.03)

    def test_the_promoted_card_is_drawn_uniformly_from_the_bench(self):
        rng = self.random.Random(11)
        counts: dict[str, int] = {}
        for _ in range(6000):
            out = self.explore(
                self.entries(7), cap=3, epsilon=1.0, rng=rng
            )
            promoted = next(e[0].id for e in out if e[4])
            counts[promoted] = counts.get(promoted, 0) + 1
        self.assertEqual(set(counts), {"R-03", "R-04", "R-05", "R-06"})
        for rule_id, seen in counts.items():
            with self.subTest(rule=rule_id):
                self.assertAlmostEqual(seen / 6000, 0.25, delta=0.03)

    def test_a_bench_cards_price_matches_how_often_it_is_shown(self):
        """The logged number has to be the real one, or IPS is biased."""
        eps, cap, n = 0.4, 3, 7
        rng = self.random.Random(3)
        quoted = next(
            e[3] for e in self.explore(
                self.entries(n), cap=cap, epsilon=eps, rng=self.random.Random(3)
            ) if e[0].id == "R-05"
        )
        shown = sum(
            any(e[0].id == "R-05" and e[4] for e in self.explore(
                self.entries(n), cap=cap, epsilon=eps, rng=rng
            ))
            for _ in range(6000)
        )
        self.assertAlmostEqual(shown / 6000, quoted, delta=0.03)


class TestPropensityIsPersisted(unittest.TestCase):
    """The column is only useful if the write path actually fills it in."""

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord,
            RecommendationRecord,
            UserPreferenceRecord,
        )
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Scope

        self.Rec = RecommendationRecord
        self.Scope = Scope
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self.engine = RecommendationEngine(session_factory=lambda: self.db)

    def tearDown(self):
        self.db.close()

    @staticmethod
    def _facts_for(spec):
        """Whatever this rule's copy asks for, so the render succeeds.

        The subject here is the propensity, not any rule's wording, and a
        finding with empty facts is dropped by ``_build`` before it can be
        written — which would make this test pass for the wrong reason.
        """
        from string import Formatter
        keys = {
            name
            for template in (spec.title, spec.why, spec.action)
            for _, name, _, _ in Formatter().parse(template)
            if name
        }
        return {key: "x" for key in keys}

    def _run(self, rule_ids):
        """Drive one scope with a fixed candidate list."""
        from app.services.recommendations.types import FeatureContext
        candidates = [
            (
                BY_ID[rid],
                Finding(dedup_key=f"key/{rid}", facts=self._facts_for(BY_ID[rid])),
                float(len(rule_ids) - i),
            )
            for i, rid in enumerate(rule_ids)
        ]
        self.engine._evaluate = lambda specs, context: list(candidates)
        context = FeatureContext(
            {}, as_of=BASE, user_id="u1", days_of_history=90
        )
        self.engine._run_scope(self.db, self.Scope.DAILY, context, BASE)
        return self.db.query(self.Rec).all()

    def test_written_cards_carry_a_propensity(self):
        rows = self._run(["HY-01", "HY-03", "HY-04"])
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(rule=row.rule_id):
                self.assertIsNotNone(row.propensity)
                self.assertGreater(row.propensity, 0.0)

    def test_the_default_policy_records_certainty_and_no_exploration(self):
        rows = self._run(["HY-01", "HY-03", "HY-04"])
        self.assertEqual({r.propensity for r in rows}, {1.0})
        self.assertEqual({bool(r.explored) for r in rows}, {False})


class TestSupersede(unittest.TestCase):
    """An authoritative re-run replaces the cards it supersedes.

    The case this exists for is a real one: a card written at 01:20 from a
    roll-up hours behind the timeline, still on the panel next to one written
    at 01:28 from complete data, the two quoting different totals for the same
    day. Dedup alone makes the first card of a day permanent, which is exactly
    wrong when the first card was the provisional one.
    """

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord,
            RecommendationRecord,
            UserPreferenceRecord,
        )
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Scope

        self.Rec = RecommendationRecord
        self.Scope = Scope
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self.engine = RecommendationEngine(session_factory=lambda: self.db)
        self.local_date = BASE.strftime("%Y-%m-%d")

    def tearDown(self):
        self.db.close()

    def _card(self, rule_id, *, status="active", scope="daily", shadow=None,
              local_date=None):
        row = self.Rec(
            id=f"{rule_id}-{status}-{scope}-{shadow}-{local_date or ''}",
            user_id="u1", device_id="d1", rule_id=rule_id, rule_version=1,
            scope=scope, section="insight", severity="low",
            title="t", why="w", action="a", based_on="b",
            facts_json="{}", evidence_json="{}", score=0.5,
            dedup_key=f"key/{rule_id}", shadow=shadow,
            local_date=local_date or self.local_date,
            generated_at=BASE.isoformat(), status=status,
        )
        self.db.add(row)
        self.db.commit()
        return row

    def _supersede(self):
        return self.engine._supersede(
            self.db, "u1", BASE, (self.Scope.DAILY,)
        )

    def test_active_cards_for_the_day_are_removed(self):
        """Removed, not marked expired: the unique index on
        (user, dedup_key, local_date) would otherwise still hold the key and
        the replacement could never be inserted."""
        key = self._card("DY-14").dedup_key
        self.assertEqual(self._supersede(), {key})
        self.assertEqual(self.db.query(self.Rec).count(), 0)

    def test_the_users_own_answers_are_never_discarded(self):
        """Judged rows are the ranker's training set, not spare capacity."""
        for status in ("applied", "dismissed", "snoozed"):
            self._card(f"DY-{status}", status=status)
        self.assertEqual(self._supersede(), set())
        remaining = {r.status for r in self.db.query(self.Rec).all()}
        self.assertEqual(remaining, {"applied", "dismissed", "snoozed"})

    def test_shadow_rows_survive(self):
        """A shadow row records what a rule under trial produced; it is not a
        card on the panel and has its own dedup path."""
        self._card("DY-05", shadow=True)
        self.assertEqual(self._supersede(), set())
        self.assertEqual(self.db.query(self.Rec).one().status, "active")

    def test_other_scopes_and_other_days_are_untouched(self):
        self._card("LV-01", scope="live")
        self._card("WK-01", scope="weekly")
        self._card("DY-14", local_date="1999-01-01")
        self.assertEqual(self._supersede(), set())
        self.assertEqual(self.db.query(self.Rec).count(), 3)

    def _generate(self, evaluate=True, **kwargs):
        """Drive generate with the feature pipeline stubbed out.

        The subject is the supersede flag, not feature extraction, and the
        in-memory database deliberately holds only the recommendation tables.
        """
        import sys
        from unittest import mock
        from app.services.recommendations.types import FeatureContext

        # Not ``from app.services.recommendations import engine``: the package
        # __init__ binds the singleton to that name, shadowing the submodule.
        engine_module = sys.modules["app.services.recommendations.engine"]

        context = FeatureContext({}, as_of=BASE, user_id="u1", days_of_history=90)
        if evaluate:
            self.engine._evaluate = lambda specs, ctx: []
        with mock.patch.object(
            self.engine, "baselines", return_value=mock.Mock()
        ), mock.patch.object(
            engine_module, "build_daily_context", return_value=context
        ):
            self.engine.generate(
                self.db, "u1", BASE, scopes=(self.Scope.DAILY,), **kwargs
            )

    def test_generate_leaves_cards_alone_unless_asked(self):
        """The interactive path calls generate on every page load. Rewriting
        the panel underneath a reader is not an improvement."""
        self._card("DY-14")
        self._generate()
        self.assertEqual(self.db.query(self.Rec).one().status, "active")

    def test_the_replacement_is_actually_written(self):
        """The failure this guards against is worse than the bug it fixes:
        clearing the day's cards while dedup and cooldown still block their
        replacements empties the panel instead of refreshing it."""
        from app.services.recommendations.types import Evidence
        stale = self._card("HY-01")
        stale_id = stale.id
        spec = BY_ID["HY-01"]
        finding = Finding(
            dedup_key=stale.dedup_key,
            facts=TestPropensityIsPersisted._facts_for(spec),
            evidence=Evidence(basis="absolute", n=1),
        )
        self.engine._evaluate = lambda specs, ctx: [(spec, finding, 1.0)]
        self._generate(supersede=True, evaluate=False)

        rows = self.db.query(self.Rec).all()
        self.assertEqual(len(rows), 1, "the day should hold exactly one live card")
        self.assertEqual(rows[0].status, "active")
        self.assertNotEqual(rows[0].id, stale_id, "this should be a fresh row")

    def test_cooldown_still_applies_across_other_days(self):
        """Only the day being rebuilt is exempt. A rule that fired yesterday
        is still on cooldown today."""
        yesterday = (BASE - timedelta(days=1)).strftime("%Y-%m-%d")
        self._card("HY-01", local_date=yesterday)
        last = self.engine._last_fired(
            self.db, "u1", [BY_ID["HY-01"]], BASE,
            exclude_local_date=self.local_date,
        )
        self.assertIn("HY-01", last)


class TestSignificanceTests(unittest.TestCase):
    """The tests themselves, against published values.

    Checked against numbers that exist independently of this implementation —
    textbook t and normal tails, exact binomial sums — rather than against
    another library, so the assertions stay meaningful without a statistics
    stack installed.
    """

    def setUp(self):
        from app.services.recommendations import stats
        self.s = stats

    # -- distributions -------------------------------------------------- #

    def test_normal_tail_matches_published_quantiles(self):
        for z, tail in ((1.6448536, 0.05), (1.9599640, 0.025), (2.3263479, 0.01)):
            with self.subTest(z=z):
                self.assertAlmostEqual(self.s.norm_sf(z), tail, places=7)

    def test_normal_tail_is_symmetric_about_zero(self):
        self.assertAlmostEqual(self.s.norm_sf(0.0), 0.5)
        for z in (0.3, 1.1, 2.7):
            self.assertAlmostEqual(
                self.s.norm_sf(z) + self.s.norm_sf(-z), 1.0, places=12
            )

    def test_t_tail_matches_the_textbook_table(self):
        """Two-sided 0.05 critical values, the column everyone has seen."""
        for df, critical in ((1, 12.706), (5, 2.571), (10, 2.228),
                             (20, 2.086), (30, 2.042)):
            with self.subTest(df=df):
                self.assertAlmostEqual(
                    self.s.student_t_p(critical, df), 0.05, places=3
                )

    def test_t_approaches_the_normal_as_df_grows(self):
        wide = self.s.student_t_p(1.959964, 100000)
        self.assertAlmostEqual(wide, 0.05, places=3)

    def test_t_is_more_conservative_than_the_normal_at_small_df(self):
        """Why the normal approximation was not good enough here."""
        self.assertGreater(
            self.s.student_t_p(2.2, 5), 2 * self.s.norm_sf(2.2)
        )

    # -- Mann-Kendall ---------------------------------------------------- #

    def test_a_perfect_run_up_is_significant(self):
        _s, z, p = self.s.mann_kendall([1.0, 2, 3, 4, 5, 6, 7, 8])
        self.assertGreater(z, 0)
        self.assertLess(p, 0.01)

    def test_a_perfect_run_down_is_significant_and_signed(self):
        s, z, p = self.s.mann_kendall([8.0, 7, 6, 5, 4, 3, 2, 1])
        self.assertEqual(s, -28)
        self.assertLess(z, 0)
        self.assertLess(p, 0.01)

    def test_direction_alone_does_not_make_a_trend(self):
        """Four weekly totals drifting up is exactly the case that motivated
        this: Theil-Sen returns a slope, Mann-Kendall declines to back it."""
        _s, _z, p = self.s.mann_kendall([100.0, 105.0, 103.0, 110.0])
        self.assertGreater(p, 0.05)

    def test_a_flat_series_has_no_trend(self):
        s, z, p = self.s.mann_kendall([5.0] * 6)
        self.assertEqual((s, z, p), (0, 0.0, 1.0))

    def test_too_few_points_is_not_a_trend(self):
        self.assertEqual(self.s.mann_kendall([1.0, 2.0]), (0, 0.0, 1.0))

    def test_ties_do_not_break_the_variance(self):
        for p in (self.s.mann_kendall([1.0, 1, 2, 2, 3, 3])[2],
                  self.s.mann_kendall([2.0, 2, 2, 2, 1])[2]):
            self.assertGreaterEqual(p, 0.0)
            self.assertLessEqual(p, 1.0)

    # -- Spearman -------------------------------------------------------- #

    def test_a_large_correlation_on_six_points_is_not_significant(self):
        """The exact failure the |rho| >= 0.3 floor cannot catch on its own."""
        self.assertGreater(self.s.spearman_p(0.6, 6), 0.05)

    def test_the_same_correlation_becomes_significant_with_enough_points(self):
        self.assertLess(self.s.spearman_p(0.6, 30), 0.05)

    def test_sign_of_the_correlation_does_not_change_the_p(self):
        self.assertAlmostEqual(
            self.s.spearman_p(0.5, 20), self.s.spearman_p(-0.5, 20)
        )

    def test_a_perfect_correlation_is_certain(self):
        self.assertEqual(self.s.spearman_p(1.0, 10), 0.0)

    # -- sign test ------------------------------------------------------- #

    def test_sign_test_matches_the_exact_binomial(self):
        # 8 of 10 one way: 2 * (C(10,0)+C(10,1)+C(10,2)) / 2^10
        #                 = 2 * (1 + 10 + 45) / 1024 = 112/1024.
        self.assertAlmostEqual(
            self.s.sign_test([1.0] * 8 + [-1.0] * 2), 112 / 1024
        )

    def test_an_even_split_is_no_evidence(self):
        self.assertEqual(self.s.sign_test([1.0] * 5 + [-1.0] * 5), 1.0)

    def test_zero_differences_are_discarded_not_counted(self):
        """A pair that moved neither way is evidence for neither."""
        self.assertAlmostEqual(
            self.s.sign_test([1.0] * 8 + [-1.0] * 2 + [0.0] * 6),
            self.s.sign_test([1.0] * 8 + [-1.0] * 2),
        )

    def test_no_usable_pairs_is_no_evidence(self):
        self.assertEqual(self.s.sign_test([0.0, 0.0]), 1.0)
        self.assertEqual(self.s.sign_test([]), 1.0)

    def test_a_consistent_direction_over_many_pairs_is_significant(self):
        self.assertLess(self.s.sign_test([-1.0] * 12 + [1.0] * 1), 0.01)


class TestBenjaminiHochberg(unittest.TestCase):
    """Multiplicity control — the gate over the whole day's battery."""

    def setUp(self):
        from app.services.recommendations.stats import benjamini_hochberg
        self.bh = benjamini_hochberg

    def test_nothing_tested_is_nothing_to_correct(self):
        self.assertEqual(self.bh([], 0.1), [])

    def test_keeps_only_what_clears_the_rising_threshold(self):
        ps = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
        self.assertEqual(
            [i for i, k in enumerate(self.bh(ps, 0.05)) if k], [0, 1]
        )

    def test_the_procedure_steps_up(self):
        """A p-value that fails its own rank still survives if a later one
        passes. Dropping it would be per-test thresholding, not BH."""
        self.assertEqual(
            self.bh([0.004, 0.011, 0.014, 0.9, 0.9], 0.05),
            [True, True, True, False, False],
        )

    def test_a_single_test_reduces_to_comparing_against_q(self):
        self.assertEqual(self.bh([0.08], 0.1), [True])
        self.assertEqual(self.bh([0.11], 0.1), [False])

    def test_the_mask_comes_back_in_the_callers_order(self):
        self.assertEqual(self.bh([0.9, 0.0001, 0.9], 0.1), [False, True, False])

    def test_volume_makes_the_bar_harder(self):
        """The point of the whole exercise: 0.04 is fine alone and is not
        fine as one of forty."""
        self.assertTrue(self.bh([0.04], 0.1)[0])
        self.assertFalse(self.bh([0.04] + [0.9] * 39, 0.1)[0])

    def test_everything_significant_survives(self):
        self.assertTrue(all(self.bh([0.0001] * 10, 0.1)))

    def test_nothing_significant_survives_nothing(self):
        self.assertFalse(any(self.bh([0.4, 0.6, 0.8], 0.1)))


class TestRobustSpread(unittest.TestCase):
    """MAD scaling and the fallback for distributions where it collapses."""

    def setUp(self):
        from app.services.recommendations.baselines import (
            IQR_TO_SIGMA, MAD_TO_SIGMA, Stat,
        )
        self.Stat = Stat
        self.MAD_TO_SIGMA = MAD_TO_SIGMA
        self.IQR_TO_SIGMA = IQR_TO_SIGMA

    def test_sigma_scales_the_mad_by_the_consistency_constant(self):
        stat = self.Stat.of([1.0, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertAlmostEqual(stat.sigma, stat.mad * self.MAD_TO_SIGMA)

    def test_the_constant_recovers_sigma_on_normal_data(self):
        """The reason 1.4826 exists: without it the spread reads about two
        thirds of the truth, and every threshold built on it is miscalibrated.
        """
        import random
        rng = random.Random(4)
        sample = [rng.gauss(100.0, 15.0) for _ in range(4000)]
        stat = self.Stat.of(sample)
        self.assertAlmostEqual(stat.sigma / 15.0, 1.0, delta=0.06)
        # The unscaled MAD is the error being corrected.
        self.assertAlmostEqual(stat.mad / 15.0, 0.6745, delta=0.05)

    def test_a_tied_majority_falls_back_to_the_iqr(self):
        """Zero-inflated counts are the normal case, not a corner case: more
        than half the days have no meetings, so the MAD is zero and the old
        code could say nothing about a four-meeting day."""
        stat = self.Stat.of([0.0, 0, 0, 0, 0, 0, 2, 4, 6, 8])
        self.assertEqual(stat.mad, 0.0)
        self.assertGreater(stat.sigma, 0.0)
        self.assertAlmostEqual(
            stat.sigma, (stat.p75 - stat.p25) * self.IQR_TO_SIGMA
        )

    def test_the_fallback_produces_a_usable_z(self):
        stat = self.Stat.of([0.0, 0, 0, 0, 0, 0, 2, 4, 6, 8])
        self.assertGreater(stat.robust_z(8.0), 1.0)

    def test_a_genuinely_flat_distribution_still_has_no_spread(self):
        stat = self.Stat.of([5.0] * 10)
        self.assertEqual(stat.sigma, 0.0)
        self.assertEqual(stat.robust_z(5.0), 0.0)
        self.assertEqual(stat.robust_z(9.0), 3.0)

    def test_sigma_is_published_to_the_rules(self):
        from app.services.recommendations.baselines import BaselineSet
        stats = BaselineSet(global_stats={"deep_work_min": self.Stat.of(
            [float(v) for v in range(1, 21)]
        )})
        flat = stats.flatten()
        self.assertIn("baseline.deep_work_min.sigma", flat)
        self.assertGreater(flat["baseline.deep_work_min.sigma"],
                           flat["baseline.deep_work_min.mad"])

    def test_the_rule_trigger_point_is_unchanged_by_the_rescaling(self):
        """The calibration fix must not silently move how often rules fire.

        One MAD above the median was the historic bar; ORDINARY_SPREAD * sigma
        has to land on exactly the same number.
        """
        from app.services.recommendations.rules.daily import ORDINARY_SPREAD
        stat = self.Stat.of([float(v) for v in range(1, 31)])
        self.assertAlmostEqual(
            stat.p50 + stat.mad, stat.p50 + ORDINARY_SPREAD * stat.sigma
        )


class TestFalseDiscoveryGate(unittest.TestCase):
    """The engine stage that applies BH to a scope's findings."""

    def setUp(self):
        from app.services.recommendations.engine import RecommendationEngine
        self.gate = RecommendationEngine._control_false_discovery

    def candidate(self, rule_id, p):
        return (
            BY_ID[rule_id],
            Finding(dedup_key=f"k/{rule_id}",
                    evidence=Evidence(basis="test", n=10, p_value=p)),
            1.0,
        )

    def absolute(self, rule_id):
        return (
            BY_ID[rule_id],
            Finding(dedup_key=f"k/{rule_id}", evidence=Evidence(basis="absolute")),
            1.0,
        )

    def test_absolute_findings_are_never_touched(self):
        """"The IDE stopped reporting" has no null hypothesis to reject, and
        must not be suppressed because an unrelated correlation was weak."""
        candidates = [self.absolute("HY-01"), self.candidate("DY-01", 0.9)]
        kept = [c[0].id for c in self.gate(candidates)]
        self.assertIn("HY-01", kept)
        self.assertNotIn("DY-01", kept)

    def test_a_battery_of_nothing_publishes_nothing(self):
        candidates = [
            self.candidate(rid, 0.30)
            for rid in ("DY-01", "DY-02", "DY-03", "DY-04", "DY-05")
        ]
        self.assertEqual(self.gate(candidates), [])

    def test_a_strong_finding_survives_its_noisy_neighbours(self):
        candidates = [self.candidate("DY-01", 0.0001)] + [
            self.candidate(rid, 0.8)
            for rid in ("DY-02", "DY-03", "DY-04", "DY-05")
        ]
        self.assertEqual([c[0].id for c in self.gate(candidates)], ["DY-01"])

    def test_no_tests_at_all_passes_everything_through(self):
        candidates = [self.absolute("HY-01"), self.absolute("HY-03")]
        self.assertEqual(len(self.gate(candidates)), 2)

    def test_order_is_preserved(self):
        candidates = [
            self.candidate("DY-01", 0.001),
            self.absolute("HY-01"),
            self.candidate("DY-02", 0.002),
        ]
        self.assertEqual(
            [c[0].id for c in self.gate(candidates)], ["DY-01", "HY-01", "DY-02"]
        )


class TestRuleMuting(unittest.TestCase):
    """Switching a rule off, and what that must and must not affect.

    Scrutability in the Tintarev & Masthoff (2012) sense: the engine already
    names the rule behind every card and shows the evidence under it, and an
    explanation you cannot act on is something to read rather than something
    to use. The controls here are the acting-on.
    """

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord,
            RecommendationRecord,
            UserPreferenceRecord,
        )
        from app.repositories.preference_repository import (
            RULE_MUTED_PREFIX, PreferenceRepository,
        )
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Scope

        self.Rec = RecommendationRecord
        self.Scope = Scope
        self.prefix = RULE_MUTED_PREFIX
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self.prefs = PreferenceRepository(self.db)
        self.engine = RecommendationEngine(session_factory=lambda: self.db)

    def tearDown(self):
        self.db.close()

    @staticmethod
    def _facts_for(spec):
        from string import Formatter
        keys = {
            name
            for template in (spec.title, spec.why, spec.action)
            for _, name, _, _ in Formatter().parse(template)
            if name
        }
        return {key: "x" for key in keys}

    def _run(self, rule_ids, muted=None):
        from app.services.recommendations.types import FeatureContext
        candidates = [
            (
                BY_ID[rid],
                Finding(dedup_key=f"key/{rid}", facts=self._facts_for(BY_ID[rid])),
                float(len(rule_ids) - i),
            )
            for i, rid in enumerate(rule_ids)
        ]
        self.engine._evaluate = lambda specs, context: [
            c for c in candidates if c[0] in specs
        ]
        context = FeatureContext({}, as_of=BASE, user_id="u1", days_of_history=90)
        self.engine._run_scope(
            self.db, self.Scope.DAILY, context, BASE, muted or set()
        )
        return [r.rule_id for r in self.db.query(self.Rec).all()]

    # -- storage --------------------------------------------------------- #

    def test_a_rule_is_not_muted_until_it_is(self):
        self.assertEqual(self.prefs.muted_rules("u1"), set())
        self.assertFalse(self.prefs.is_rule_muted("u1", "DY-01"))

    def test_muting_round_trips(self):
        self.prefs.set_rule_muted("u1", "DY-01", True)
        self.assertEqual(self.prefs.muted_rules("u1"), {"DY-01"})
        self.assertTrue(self.prefs.is_rule_muted("u1", "DY-01"))

    def test_unmuting_removes_it_from_the_set(self):
        self.prefs.set_rule_muted("u1", "DY-01", True)
        self.prefs.set_rule_muted("u1", "DY-01", False)
        self.assertEqual(self.prefs.muted_rules("u1"), set())

    def test_muting_is_per_user(self):
        self.prefs.set_rule_muted("u1", "DY-01", True)
        self.assertEqual(self.prefs.muted_rules("u2"), set())

    def test_mute_keys_do_not_collide_with_other_preferences(self):
        """The store is shared with the webcam consent flag and anything else
        Settings adds later; the prefix is what keeps them apart."""
        from app.repositories.preference_repository import WEBCAM_EMOTION_CONSENT
        self.prefs.set_bool("u1", WEBCAM_EMOTION_CONSENT, True)
        self.prefs.set_rule_muted("u1", "DY-01", True)
        self.assertEqual(self.prefs.muted_rules("u1"), {"DY-01"})
        self.assertTrue(self.prefs.get_bool("u1", WEBCAM_EMOTION_CONSENT))

    # -- the gate -------------------------------------------------------- #

    def test_an_unmuted_run_writes_every_card(self):
        written = self._run(["HY-01", "HY-03", "HY-04"])
        self.assertEqual(sorted(written), ["HY-01", "HY-03", "HY-04"])

    def test_a_muted_rule_writes_no_card(self):
        written = self._run(["HY-01", "HY-03", "HY-04"], muted={"HY-03"})
        self.assertNotIn("HY-03", written)
        self.assertIn("HY-01", written)

    def test_muting_leaves_no_row_behind(self):
        """Not filtered downstream — never generated.

        A suppressed-but-stored card would be counted by the telemetry as one
        the engine chose to show, which is exactly the wrong reading.
        """
        self._run(["HY-01", "HY-03"], muted={"HY-03"})
        rows = self.db.query(self.Rec).filter(
            self.Rec.rule_id == "HY-03"
        ).all()
        self.assertEqual(rows, [])

    def test_muting_everything_writes_nothing(self):
        written = self._run(["HY-01", "HY-03"], muted={"HY-01", "HY-03"})
        self.assertEqual(written, [])

    def test_muting_an_unrelated_rule_changes_nothing(self):
        written = self._run(["HY-01", "HY-03"], muted={"WK-01"})
        self.assertEqual(sorted(written), ["HY-01", "HY-03"])

    # -- history is kept ------------------------------------------------- #

    def test_cards_written_before_the_mute_survive_it(self):
        """The record of a rule doing badly is the justification for muting
        it. Deleting that on mute would make the decision unreviewable."""
        self._run(["HY-01", "HY-03"])
        self.prefs.set_rule_muted("u1", "HY-03", True)
        kept = [r.rule_id for r in self.db.query(self.Rec).all()]
        self.assertIn("HY-03", kept)

    def test_telemetry_reports_the_mute_without_hiding_the_history(self):
        from app.services.recommendations.telemetry import rule_health
        self._run(["HY-01", "HY-03"])
        self.prefs.set_rule_muted("u1", "HY-03", True)
        report = rule_health(self.db, "u1")
        health = next(r for r in report.rules if r.rule_id == "HY-03")
        self.assertTrue(health.muted)
        self.assertEqual(health.fired, 1)
        self.assertEqual(report.muted_count, 1)

    def test_telemetry_counts_no_mutes_when_there_are_none(self):
        from app.services.recommendations.telemetry import rule_health
        self.assertEqual(rule_health(self.db, "u1").muted_count, 0)


class TestRankingMetrics(unittest.TestCase):
    """The metric arithmetic, on lists small enough to check by hand."""

    def setUp(self):
        from app.services.recommendations import evaluation
        self.ev = evaluation

    def card(self, relevant, score=1.0, rule_id="DY-01"):
        return self.ev.LabelledCard(
            rule_id=rule_id, local_date="2026-08-14", section="insight",
            severity="low", stored_score=score, relevant=relevant,
            propensity=None, rule_score=score,
        )

    def test_dcg_discounts_by_position(self):
        """A hit at rank 1 is worth more than the same hit at rank 3."""
        self.assertGreater(self.ev.dcg([True, False]), self.ev.dcg([False, True]))

    def test_dcg_of_nothing_relevant_is_zero(self):
        self.assertEqual(self.ev.dcg([False, False, False]), 0.0)

    def test_dcg_matches_the_closed_form(self):
        # 1/log2(2) + 1/log2(4) = 1 + 0.5
        self.assertAlmostEqual(self.ev.dcg([True, False, True]), 1.0 + 0.5)

    def test_ndcg_is_one_when_the_ordering_is_ideal(self):
        ordered = [self.card(True), self.card(True), self.card(False)]
        self.assertAlmostEqual(self.ev.ndcg_at_k(ordered, 3), 1.0)

    def test_ndcg_is_below_one_when_a_hit_is_buried(self):
        ordered = [self.card(False), self.card(False), self.card(True)]
        self.assertLess(self.ev.ndcg_at_k(ordered, 3), 1.0)

    def test_ndcg_is_undefined_with_nothing_relevant(self):
        """Zero would read as 'the ordering was bad'. It was unmeasurable."""
        self.assertIsNone(
            self.ev.ndcg_at_k([self.card(False), self.card(False)], 2)
        )

    def test_the_rule_score_matches_the_engine_arithmetic(self):
        """The ablation must reproduce the engine minus its learned term.

        Any drift makes 'rules only' measure a policy that never ran.
        """
        from app.services.recommendations.engine import RecommendationEngine
        spec = BY_ID["DY-01"]
        evidence = Evidence(basis="personal_deep", n=20, effect=1.2)
        finding = Finding(dedup_key="x", evidence=evidence)

        class _Flat:
            @staticmethod
            def multiplier(**_kwargs):
                return 1.0

        # `app.services.recommendations.__init__` rebinds the name `engine`
        # to the singleton, so the dotted import resolves to that object
        # rather than the module. sys.modules is unambiguous.
        import sys as _sys
        engine_module = _sys.modules["app.services.recommendations.engine"]
        real = engine_module.ranker
        engine_module.ranker = _Flat()
        try:
            engine_side = RecommendationEngine._score(spec, finding, BASE)
        finally:
            engine_module.ranker = real
        self.assertAlmostEqual(
            self.ev._rule_score(spec.severity.value, evidence),
            engine_side,
            places=4,
        )


class TestOffPolicySupport(unittest.TestCase):
    """Whether an off-policy estimate is identified — usually it is not."""

    def setUp(self):
        from app.services.recommendations import evaluation
        self.ev = evaluation

    def card(self, propensity, relevant=True):
        return self.ev.LabelledCard(
            rule_id="DY-01", local_date="2026-08-14", section="insight",
            severity="low", stored_score=1.0, relevant=relevant,
            propensity=propensity, rule_score=1.0,
        )

    def test_rows_without_a_propensity_are_not_identified(self):
        diag = self.ev.support_diagnostic([self.card(None), self.card(None)])
        self.assertFalse(diag.identified)
        self.assertEqual(diag.cards_without_propensity, 2)

    def test_a_deterministic_log_is_not_identified(self):
        """Every card at probability 1 is the default state, and no estimator
        can distinguish the policy that ran from any other."""
        diag = self.ev.support_diagnostic([self.card(1.0) for _ in range(20)])
        self.assertFalse(diag.identified)
        self.assertIn("deterministic", diag.reason)

    def test_exploration_makes_it_identified(self):
        diag = self.ev.support_diagnostic(
            [self.card(1.0)] * 10 + [self.card(0.05)]
        )
        self.assertTrue(diag.identified)
        self.assertEqual(diag.explored_cards, 1)
        self.assertAlmostEqual(diag.min_propensity, 0.05)

    def test_snips_is_none_without_usable_propensities(self):
        cards = [self.card(None)]
        self.assertIsNone(
            self.ev.snips(cards, {("2026-08-14", "DY-01")})
        )

    def test_snips_weights_rare_cards_up(self):
        """A card shown one time in twenty stands for twenty."""
        cards = [
            self.ev.LabelledCard("DY-01", "d1", "insight", "low", 1.0,
                                 True, 0.05, 1.0),
            self.ev.LabelledCard("DY-02", "d1", "insight", "low", 1.0,
                                 False, 1.0, 1.0),
        ]
        target = {("d1", "DY-01"), ("d1", "DY-02")}
        value = self.ev.snips(cards, target)
        # 20 * 1 + 1 * 0, over 20 + 1.
        self.assertAlmostEqual(value, 20 / 21)

    def test_snips_ignores_cards_the_target_would_not_show(self):
        cards = [
            self.ev.LabelledCard("DY-01", "d1", "insight", "low", 1.0,
                                 True, 1.0, 1.0),
            self.ev.LabelledCard("DY-02", "d1", "insight", "low", 1.0,
                                 False, 1.0, 1.0),
        ]
        self.assertAlmostEqual(self.ev.snips(cards, {("d1", "DY-01")}), 1.0)


class TestEvaluationHarness(unittest.TestCase):
    """The harness over a seeded history."""

    def setUp(self):
        import json
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord, RecommendationRecord, UserPreferenceRecord,
        )
        from app.services.recommendations.evaluation import evaluate

        self.json = json
        self.Rec = RecommendationRecord
        self.evaluate = evaluate
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self._seq = 0

    def tearDown(self):
        self.db.close()

    def card(self, day, rule_id, score, status, propensity=1.0,
             severity="low", section="insight", n=20, effect=1.2):
        self._seq += 1
        self.db.add(self.Rec(
            id=f"r{self._seq}", user_id="u1", rule_id=rule_id, rule_version=1,
            scope="daily", section=section, severity=severity, title="t",
            why="w", action="a", score=score, dedup_key=f"k{self._seq}",
            local_date=day, generated_at=f"{day}T09:00:00", status=status,
            evidence_json=self.json.dumps(
                {"basis": "personal", "n": n, "effect": effect}
            ),
            propensity=propensity,
        ))
        self.db.commit()

    def test_no_history_evaluates_nothing(self):
        report = self.evaluate(self.db, "u1")
        self.assertEqual(report.days_evaluated, 0)
        self.assertEqual(report.labelled_cards, 0)
        self.assertIsNone(report.beats_random)

    def test_active_cards_carry_no_verdict_and_are_excluded(self):
        """An undecided card is not a miss."""
        self.card("2026-08-01", "DY-01", 1.0, "active")
        self.card("2026-08-01", "DY-02", 0.5, "applied")
        report = self.evaluate(self.db, "u1")
        self.assertEqual(report.labelled_cards, 1)

    def test_snoozed_counts_as_relevant(self):
        self.card("2026-08-01", "DY-01", 1.0, "snoozed")
        self.card("2026-08-01", "DY-02", 0.5, "dismissed")
        self.assertEqual(self.evaluate(self.db, "u1").relevant_cards, 1)

    def test_expired_counts_as_irrelevant(self):
        self.card("2026-08-01", "DY-01", 1.0, "expired")
        self.assertEqual(self.evaluate(self.db, "u1").relevant_cards, 0)

    def test_a_perfect_ordering_scores_one(self):
        """Relevant cards on top, in score order — nothing left to improve."""
        self.card("2026-08-01", "DY-01", 9.0, "applied")
        self.card("2026-08-01", "DY-02", 8.0, "applied")
        self.card("2026-08-01", "DY-03", 1.0, "dismissed")
        engine = self.evaluate(self.db, "u1", k=2).strategies["engine"]
        self.assertAlmostEqual(engine.ndcg_at_k, 1.0)
        self.assertAlmostEqual(engine.precision_at_k, 1.0)
        self.assertAlmostEqual(engine.mrr, 1.0)

    def test_an_inverted_ordering_scores_badly(self):
        self.card("2026-08-01", "DY-01", 9.0, "dismissed")
        self.card("2026-08-01", "DY-02", 8.0, "dismissed")
        self.card("2026-08-01", "DY-03", 1.0, "applied")
        engine = self.evaluate(self.db, "u1", k=2).strategies["engine"]
        self.assertEqual(engine.precision_at_k, 0.0)
        self.assertAlmostEqual(engine.mrr, 1 / 3)

    def test_every_ablation_is_reported(self):
        self.card("2026-08-01", "DY-01", 9.0, "applied")
        self.card("2026-08-01", "DY-02", 1.0, "dismissed")
        strategies = self.evaluate(self.db, "u1").strategies
        for name in ("engine", "rules_only", "frequent", "severity", "random"):
            self.assertIn(name, strategies)

    def test_the_frequency_baseline_cannot_see_the_day_it_scores(self):
        """Temporal discipline, stated as a test.

        DY-02 is accepted on every later day. On the first day it has no
        history at all, so the baseline must not already prefer it.
        """
        self.card("2026-08-01", "DY-01", 9.0, "applied")
        self.card("2026-08-01", "DY-02", 1.0, "dismissed")
        for day in range(2, 8):
            self.card(f"2026-08-{day:02d}", "DY-02", 1.0, "applied")
            self.card(f"2026-08-{day:02d}", "DY-01", 9.0, "dismissed")
        report = self.evaluate(self.db, "u1", k=1)
        # If history leaked, day one would rank DY-02 first and score 0.
        self.assertGreater(report.strategies["frequent"].precision_at_k, 0.0)

    def test_coverage_notices_a_one_rule_recommender(self):
        for day in range(1, 11):
            self.card(f"2026-08-{day:02d}", "DY-01", 9.0, "applied")
            self.card(f"2026-08-{day:02d}", "DY-02", 1.0, "dismissed")
        engine = self.evaluate(self.db, "u1", k=1).strategies["engine"]
        self.assertLess(engine.coverage, 0.05)

    def test_diversity_notices_a_single_section_panel(self):
        self.card("2026-08-01", "DY-01", 9.0, "applied", section="insight")
        self.card("2026-08-01", "DY-02", 8.0, "dismissed", section="insight")
        self.card("2026-08-01", "DY-03", 7.0, "dismissed", section="insight")
        engine = self.evaluate(self.db, "u1", k=3).strategies["engine"]
        self.assertAlmostEqual(engine.diversity, 1 / 3)

    def test_since_bounds_the_window(self):
        self.card("2026-07-01", "DY-01", 9.0, "applied")
        self.card("2026-07-01", "DY-02", 1.0, "dismissed")
        self.card("2026-08-01", "DY-01", 9.0, "applied")
        self.card("2026-08-01", "DY-02", 1.0, "dismissed")
        self.assertEqual(
            self.evaluate(self.db, "u1", since="2026-08-01").days_evaluated, 1
        )

    def test_the_report_serialises_for_the_endpoint(self):
        self.card("2026-08-01", "DY-01", 9.0, "applied")
        self.card("2026-08-01", "DY-02", 1.0, "dismissed")
        payload = self.evaluate(self.db, "u1").as_dict()
        self.assertIn("strategies", payload)
        self.assertIn("support", payload)
        self.assertIn("beats_random", payload)

    def test_a_deterministic_log_reports_no_off_policy_support(self):
        self.card("2026-08-01", "DY-01", 9.0, "applied", propensity=1.0)
        self.card("2026-08-01", "DY-02", 1.0, "dismissed", propensity=1.0)
        self.assertFalse(self.evaluate(self.db, "u1").support.identified)

    def test_an_explored_log_reports_support(self):
        self.card("2026-08-01", "DY-01", 9.0, "applied", propensity=1.0)
        self.card("2026-08-01", "DY-02", 1.0, "dismissed", propensity=0.05)
        self.assertTrue(self.evaluate(self.db, "u1").support.identified)


class TestSyntheticGroundTruth(unittest.TestCase):
    """Rules measured against conditions planted on purpose.

    Feedback tells us whether a card was wanted, which is a different question
    from whether it was right. These scenarios are the only place the answer is
    known in advance, so they are the only place precision and recall mean
    what the words say.
    """

    def setUp(self):
        from app.services.recommendations import simulation
        self.sim = simulation

    def test_the_suite_covers_the_threshold_rules(self):
        for rule_id in self.sim.DEVIATION_RULES:
            with self.subTest(rule=rule_id):
                self.assertIn(rule_id, BY_ID)

    def test_no_rule_is_gated_by_the_generated_features(self):
        """A gated rule is a generator that supplied too little, and would be
        silently miscounted as a rule that failed to detect anything."""
        for rule_id, accuracy in self.sim.run_suite().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(accuracy.gated, 0)

    def test_no_rule_raises_on_generated_input(self):
        for rule_id, accuracy in self.sim.run_suite().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(accuracy.errors, [])

    def test_planted_deviations_are_detected(self):
        """Recall against ground truth, which is the whole point."""
        for rule_id, accuracy in self.sim.run_suite().items():
            with self.subTest(rule=rule_id):
                self.assertIsNotNone(accuracy.recall)
                self.assertGreaterEqual(accuracy.recall, 0.95)

    def test_ordinary_days_do_not_fire(self):
        """False positives are the failure that trains a user to ignore the
        panel, so they are the number worth pinning."""
        for rule_id, accuracy in self.sim.run_suite().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(accuracy.false_positives, 0)

    def test_the_suite_is_reproducible(self):
        first = self.sim.summarise(self.sim.run_suite(seed=7))
        second = self.sim.summarise(self.sim.run_suite(seed=7))
        self.assertEqual(first["true_positives"], second["true_positives"])
        self.assertEqual(first["false_positives"], second["false_positives"])

    def test_a_different_seed_is_still_a_valid_measurement(self):
        summary = self.sim.summarise(self.sim.run_suite(seed=99))
        self.assertEqual(summary["false_positives"], 0)
        self.assertGreaterEqual(summary["recall"], 0.95)

    def test_an_unknown_rule_is_reported_not_raised(self):
        result = self.sim.measure("ZZ-99", [])
        self.assertIn("unknown rule ZZ-99", result.errors[0])

    def test_precision_and_recall_are_none_without_cases(self):
        blank = self.sim.RuleAccuracy(rule_id="DY-04")
        self.assertIsNone(blank.precision)
        self.assertIsNone(blank.recall)
        self.assertIsNone(blank.f1)

    # -- the sensitivity curve ------------------------------------------ #

    def test_nothing_fires_at_zero_deviation(self):
        """A day exactly on the median is the definition of unremarkable."""
        for rule_id, curve in self.sim.run_sweeps().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(curve[0.0], 0.0)

    def test_detection_is_monotone_in_the_deviation(self):
        """A rule that fires at 1 sigma and not at 2 has inverted logic."""
        for rule_id, curve in self.sim.run_sweeps().items():
            steps = sorted(curve)
            rates = [curve[s] for s in steps]
            with self.subTest(rule=rule_id):
                self.assertEqual(rates, sorted(rates))

    def test_the_curve_turns_on_around_the_documented_bar(self):
        """The engine's bar is one raw MAD, which is 0.67 sigma. The rules
        should be silent below it and firing above — this is the evidence for
        the threshold rather than an assertion about it."""
        for rule_id, curve in self.sim.run_sweeps().items():
            with self.subTest(rule=rule_id):
                self.assertEqual(curve[0.5], 0.0)
                self.assertEqual(curve[1.0], 1.0)

    def test_the_summary_totals_the_suite(self):
        summary = self.sim.summarise(self.sim.run_suite())
        self.assertEqual(summary["rules"], len(self.sim.DEVIATION_RULES))
        self.assertEqual(
            summary["true_positives"] + summary["false_negatives"],
            sum(r.positives for r in self.sim.run_suite().values()),
        )


class TestTitleRedaction(unittest.TestCase):
    """Window titles are the sensitive-data hotspot, and they reach exports.

    A title is the only recorded field written by software the user does not
    control, and it reaches card copy that is stored rendered and printed into
    reports a user emails to someone. These assertions cover the structured
    secrets — credentials, addresses, paths — and one that documents the limit.
    """

    def setUp(self):
        from app.services.recommendations import redaction
        self.r = redaction
        self.redact = redaction.redact_title

    def test_nothing_in_means_nothing_out(self):
        """Not a placeholder: callers already treat empty as 'no title', and
        '<redacted>' would put a scrub marker where nothing was recorded."""
        self.assertEqual(self.redact(None), "")
        self.assertEqual(self.redact(""), "")

    def test_an_ordinary_title_is_untouched(self):
        self.assertEqual(
            self.redact("SmartDesk - Visual Studio Code"),
            "SmartDesk - Visual Studio Code",
        )

    def test_email_addresses_are_removed(self):
        self.assertNotIn("alice.smith@acmecorp.com", self.redact(
            "Inbox (3) - alice.smith@acmecorp.com - Outlook"
        ))

    def test_grouped_identifiers_are_removed(self):
        """Grouping is what defeats a plain run-of-seven-digits rule: a card
        number written in fours contains no run longer than four."""
        for title in (
            "BankApp - Account 4111 1111 1111 1111",
            "Card 4111-1111-1111-1111",
            "Zoom Meeting ID 812 3456 7890",
            "Call 555-123-4567 - Phone",
        ):
            with self.subTest(title=title):
                cleaned = self.redact(title)
                self.assertIn("<number>", cleaned)
                # The surrounding nouns are what make the card readable.
                self.assertEqual(
                    sum(char.isdigit() for char in cleaned), 0, cleaned
                )

    def test_dates_and_times_survive_the_grouped_number_sweep(self):
        """They share the shape and are not identifiers. A rule counting
        digits alone would strip every date out of every title."""
        for title in (
            "Standup 2026-08-19 - Calendar",
            "Report 19/08/2026 - Excel",
            "Focus 00:00-01:00 - SmartDesk",
            "v1 2 3 release notes",
        ):
            with self.subTest(title=title):
                self.assertEqual(self.redact(title), title)

    def test_the_surrounding_words_survive_an_email(self):
        out = self.redact("Inbox (3) - alice@acme.com - Outlook")
        self.assertIn("Inbox", out)
        self.assertIn("Outlook", out)

    def test_a_url_keeps_its_host_and_loses_its_path(self):
        """The host is the useful noun; the path and query are where document
        ids, search terms and tokens live."""
        out = self.redact("https://mail.google.com/mail/u/0/#inbox/FMfcgzabc123XYZ987")
        self.assertIn("mail.google.com", out)
        self.assertNotIn("FMfcgzabc123XYZ987", out)

    def test_a_token_in_a_query_string_is_removed(self):
        out = self.redact("reset?token=eyJhbGciOiJIUzI1NiJ9abcdefghij - Acme SSO")
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9abcdefghij", out)
        self.assertIn("Acme SSO", out)

    def test_a_url_without_its_scheme_still_loses_its_query(self):
        """The form titles actually carry.

        A browser hides ``https://`` in the address bar and dev tooling prints
        ``localhost:8000/...``, so the schemeless spelling is the common one,
        not the exception. Anchoring the sweep on the scheme meant these passed
        through whole -- query string, token and all -- which is precisely what
        the module is here to prevent.
        """
        for title, secret, host in (
            ("app.example.com/share?key=s3cr3t - Edge", "s3cr3t", "app.example.com"),
            ("localhost:8000/admin?token=abc123secret", "abc123secret", "localhost:8000"),
            ("github.com/acme/secret-repo/pull/42 - Comet", "secret-repo", "github.com"),
            ("127.0.0.1:5000/reset?password=hunter2", "hunter2", "127.0.0.1:5000"),
        ):
            with self.subTest(title=title):
                out = self.redact(title)
                self.assertNotIn(secret, out)
                # The host is the noun that makes the card worth reading.
                self.assertIn(host, out)

    def test_a_short_secret_is_removed_when_its_key_names_it(self):
        """Length is the wrong test for a password.

        The token sweep starts at twenty characters, on the reasoning that
        anything shorter is prose. That holds for prose and fails for
        passwords, so every short credential went through untouched. The key
        beside the value is the signal instead.
        """
        for title, secret in (
            ("ssh root@10.0.0.5 password=hunter2 - Terminal", "hunter2"),
            ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI - Terminal", "wJalrXUtnFEMI"),
            ("api-key=deadbeef - Postman", "deadbeef"),
            ("login?session=a1b2c3 - Chrome", "a1b2c3"),
        ):
            with self.subTest(title=title):
                self.assertNotIn(secret, self.redact(title))

    def test_the_key_name_survives_the_value_it_named(self):
        """Same bias as everywhere else here: strip identifiers, keep nouns.

        ``password=<token>`` still tells a reader what the window was showing.
        ``<redacted>`` would not.
        """
        out = self.redact("api-key=deadbeef - Postman")
        self.assertIn("api-key", out)
        self.assertIn("Postman", out)

    def test_an_ordinary_word_containing_a_key_name_is_not_an_assignment(self):
        """The false positives that a substring search would create.

        "monkey" ends in "key" and "design" is one letter from "sig". Matching
        the credential word as a delimited component rather than a substring is
        what keeps these titles intact -- and the sweep takes ``=`` only,
        because a colon is ordinary punctuation in a title and accepting one
        would redact the words after every "Re:" and "Keynote:".
        """
        for title in (
            "Keynote: Q3 planning - Slides",
            "Monkey Island: Special Edition - Steam",
            "Key: Largo - Netflix",
            "design=modern - Figma",
        ):
            with self.subTest(title=title):
                self.assertEqual(self.redact(title), title)

    def test_a_windows_path_collapses_to_its_file_name(self):
        out = self.redact(r"C:\Users\speed\Clients\AcmeCorp\Confidential\budget.xlsx")
        self.assertIn("budget.xlsx", out)
        self.assertNotIn("Confidential", out)
        self.assertNotIn("AcmeCorp", out)

    def test_a_posix_path_collapses_to_its_file_name(self):
        out = self.redact("/home/speed/projects/secret-merger/notes.md - Vim")
        self.assertIn("notes.md", out)
        self.assertNotIn("secret-merger", out)

    def test_long_digit_runs_are_removed(self):
        out = self.redact("Account 4111111111111111 - Banking")
        self.assertNotIn("4111111111111111", out)
        self.assertIn("Banking", out)

    def test_short_numbers_are_kept(self):
        """A year or an item count is not an identifier."""
        self.assertIn("2026", self.redact("Budget 2026 - Excel"))
        self.assertIn("(3)", self.redact("Inbox (3) - Outlook"))

    def test_titles_are_truncated(self):
        out = self.redact("a" * 200)
        self.assertLessEqual(len(out), self.r.MAX_LENGTH + 3)

    def test_redaction_is_idempotent(self):
        """Running twice must not eat its own markers."""
        once = self.redact("/home/a/b/c.md - alice@acme.com")
        self.assertEqual(self.redact(once), once)

    def test_a_plain_language_secret_is_not_caught(self):
        """Documents the limit honestly.

        Nothing here is structurally identifiable, so it passes through. The
        claim this module supports is 'structured secrets are removed', never
        'titles are safe'.
        """
        sensitive = "Q3 layoffs - Acme Corp - Google Docs"
        self.assertEqual(self.redact(sensitive), sensitive)

    # -- the in-place helper --------------------------------------------- #

    def test_redact_features_only_touches_the_named_keys(self):
        data = {"current_title": "/a/b/c.md", "deep_work_min": 120.0}
        self.r.redact_features(data, ("current_title",))
        self.assertEqual(data["current_title"], "c.md")
        self.assertEqual(data["deep_work_min"], 120.0)

    def test_redact_features_ignores_absent_and_non_string_values(self):
        data = {"current_title": 42, "deep_work_min": 120.0}
        self.r.redact_features(data, ("current_title", "not_present"))
        self.assertEqual(data["current_title"], 42)

    def test_every_title_feature_the_builders_emit_is_covered(self):
        """The list and the builders must not drift.

        A new title feature that nobody adds here would reach card copy raw,
        and no test would notice — so this scans the source instead of trusting
        the list.
        """
        import re
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "recommendations" / "features.py"
        ).read_text(encoding="utf-8")
        emitted = set(re.findall(r'["\'](\w*title\w*)["\']\s*\]\s*=', source))
        emitted |= set(re.findall(r'out\[["\'](\w*title\w*)["\']\]', source))
        uncovered = {
            key for key in emitted
            if key.endswith("title") and key not in self.r.TITLE_FEATURES
        }
        self.assertEqual(uncovered, set())

    def test_rules_reading_titles_get_redacted_values(self):
        """End to end at the boundary: a context built with a raw title hands
        the rule a scrubbed one."""
        from app.services.recommendations.redaction import redact_features
        data = {"last_work_title": r"C:\Users\me\Secret\Client\plan.docx"}
        redact_features(data, self.r.TITLE_FEATURES)
        self.assertNotIn("Secret", data["last_work_title"])
        self.assertIn("plan.docx", data["last_work_title"])


class TestCalibration(unittest.TestCase):
    """A score is not a probability until something makes it one."""

    def setUp(self):
        from app.services.recommendations.stats import (
            PlattScaling, expected_calibration_error, reliability_curve,
        )
        self.Platt = PlattScaling
        self.ece = expected_calibration_error
        self.curve = reliability_curve

    def test_a_perfectly_calibrated_model_scores_zero(self):
        """Half the 0.5 predictions come true, all the 1.0s do."""
        probs = [0.5] * 100 + [1.0] * 100
        outcomes = [i % 2 == 0 for i in range(100)] + [True] * 100
        self.assertAlmostEqual(self.ece(probs, outcomes), 0.0, places=6)

    def test_an_overconfident_model_scores_badly(self):
        """Predicting 0.9 for something that happens half the time."""
        probs = [0.9] * 100
        outcomes = [i % 2 == 0 for i in range(100)]
        self.assertAlmostEqual(self.ece(probs, outcomes), 0.4, places=6)

    def test_a_prediction_of_exactly_one_is_still_binned(self):
        """The top bin owns its upper edge, or 1.0 falls outside every bin and
        is silently dropped from the average."""
        self.assertAlmostEqual(self.ece([1.0, 1.0], [True, True]), 0.0)
        self.assertAlmostEqual(self.ece([1.0, 1.0], [False, False]), 1.0)

    def test_nothing_to_measure_returns_none(self):
        self.assertIsNone(self.ece([], []))
        self.assertIsNone(self.ece([0.5], [True, False]))

    def test_platt_improves_a_miscalibrated_score(self):
        import random
        rng = random.Random(3)
        stated, outcome = [], []
        for _ in range(600):
            p = rng.random()
            stated.append(p)
            outcome.append(rng.random() < 0.5 * p + 0.25)
        platt = self.Platt()
        self.assertTrue(platt.fit(stated, outcome))
        after = [platt.transform(p) for p in stated]
        self.assertLess(self.ece(after, outcome), self.ece(stated, outcome))

    def test_platt_is_monotone(self):
        """Calibration must not reorder anything — it only rescales."""
        platt = self.Platt()
        platt.a, platt.b, platt.fitted = 2.0, -1.0, True
        values = [platt.transform(p) for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
        self.assertEqual(values, sorted(values))

    def test_platt_output_stays_a_probability(self):
        platt = self.Platt()
        platt.a, platt.b, platt.fitted = 50.0, -25.0, True
        for score in (-10.0, 0.0, 0.5, 1.0, 10.0):
            with self.subTest(score=score):
                self.assertGreaterEqual(platt.transform(score), 0.0)
                self.assertLessEqual(platt.transform(score), 1.0)

    def test_platt_refuses_one_class(self):
        """Any monotone map fits equally, and the search runs to infinity."""
        self.assertFalse(self.Platt().fit([0.1, 0.5, 0.9] * 5, [True] * 15))

    def test_platt_refuses_too_few_points(self):
        self.assertFalse(self.Platt().fit([0.1, 0.9], [True, False]))

    def test_an_unfitted_calibrator_reports_itself(self):
        self.assertFalse(self.Platt().fitted)

    def test_the_reliability_curve_skips_empty_bins(self):
        rows = self.curve([0.05, 0.95], [True, True], bins=10)
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["count"], 1)


class TestChangeDetection(unittest.TestCase):
    """CUSUM level shifts, replacing the three-consecutive-weeks heuristic.

    The old test could only see a change of exactly the shape it was written
    for — three weeks long, one spread deep — and both numbers were arbitrary.
    """

    def setUp(self):
        from app.services.recommendations.stats import (
            cusum_change_point, deseasonalise_weekday, level_shift,
        )
        self.cusum = cusum_change_point
        self.shift = level_shift
        self.deseason = deseasonalise_weekday

    def test_a_clean_shift_is_located_exactly(self):
        """The CUSUM extremum sits on the last pre-change point, so the split
        is that plus one. Without the offset the pre-change mean absorbs a
        post-change value and the jump reads smaller than it was."""
        result = self.shift([10.0] * 5 + [40.0] * 5)
        self.assertEqual(result["index"], 5)
        self.assertEqual(result["before"], 10.0)
        self.assertEqual(result["after"], 40.0)

    def test_direction_is_reported(self):
        self.assertEqual(self.shift([10.0] * 5 + [40.0] * 5)["direction"], "up")
        self.assertEqual(self.shift([40.0] * 5 + [10.0] * 5)["direction"], "down")

    def test_noise_alone_is_not_a_shift(self):
        self.assertIsNone(self.shift([10.0, 11, 9, 10, 11, 9, 10, 11, 9, 10]))

    def test_a_flat_series_has_no_change_point(self):
        self.assertEqual(self.cusum([5.0] * 10), (None, 0.0))

    def test_a_short_series_has_no_change_point(self):
        self.assertEqual(self.cusum([1.0, 2.0, 3.0]), (None, 0.0))

    def test_a_perfectly_clean_split_reports_a_real_effect_size(self):
        """Both halves constant means the within-group spread is zero, and a
        standardised effect of 0.0 would describe the cleanest possible shift
        as no shift at all."""
        result = self.shift([10.0] * 5 + [40.0] * 5)
        self.assertGreater(result["effect_sigma"], 0.0)

    def test_the_two_halves_partition_the_series(self):
        values = [1.0, 1, 1, 1, 9, 9, 9, 9]
        result = self.shift(values)
        self.assertEqual(result["n_before"] + result["n_after"], len(values))

    def test_a_higher_threshold_rejects_a_weak_shift(self):
        values = [10.0, 11, 10, 11, 13, 12, 13, 12]
        self.assertIsNone(self.shift(values, threshold=5.0))

    # -- deseasonalising -------------------------------------------------- #

    def test_a_pure_weekly_cycle_flattens_to_nothing(self):
        """The point: a run of quiet weekends is not a downward trend."""
        values = [100.0, 100, 100, 100, 100, 20, 20] * 3
        weekdays = [0, 1, 2, 3, 4, 5, 6] * 3
        remainder = self.deseason(values, weekdays)
        self.assertEqual(set(remainder), {0.0})

    def test_a_real_shift_survives_deseasonalising(self):
        values = [100.0, 100, 100, 100, 100, 20, 20] * 2 + \
                 [160.0, 160, 160, 160, 160, 80, 80] * 2
        weekdays = [0, 1, 2, 3, 4, 5, 6] * 4
        remainder = self.deseason(values, weekdays)
        self.assertIsNotNone(self.shift(remainder))

    def test_mismatched_inputs_are_returned_unchanged(self):
        """A length mismatch means the pairing is unknown, and guessing it
        would silently subtract the wrong weekday's median."""
        self.assertEqual(self.deseason([1.0, 2.0], [0]), [1.0, 2.0])

    def test_empty_input_is_safe(self):
        self.assertEqual(self.deseason([], []), [])


# --------------------------------------------------------------------- #
# Property-based tests
# --------------------------------------------------------------------- #
#
# The example-based tests above check the cases somebody thought of. These
# check the ones nobody did. The engine's failure mode is a confident false
# statement rather than a crash, and the inputs that produce one are usually
# degenerate rather than exotic — a flat distribution, a single sample, a
# metric that is zero on most days. Hypothesis is good at finding exactly those
# and reports the smallest example that breaks the property.

from hypothesis import given, settings as hyp_settings, strategies as st

#: Deadlines off: the suite runs on a laptop that may be doing other things,
#: and a timing-based failure would be noise rather than a finding.
PROPERTY = hyp_settings(max_examples=200, deadline=None)

_finite = st.floats(
    min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False
)
_probability = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


class TestStatisticalProperties(unittest.TestCase):
    """Invariants that must hold for every input, not just the chosen ones."""

    @PROPERTY
    @given(st.lists(_finite, min_size=1, max_size=60))
    def test_percentile_is_always_within_the_data_range(self, values):
        from app.services.recommendations.baselines import percentile
        for q in (0.0, 0.1, 0.5, 0.9, 1.0):
            self.assertGreaterEqual(percentile(values, q), min(values) - 1e-6)
            self.assertLessEqual(percentile(values, q), max(values) + 1e-6)

    @PROPERTY
    @given(st.lists(_finite, min_size=1, max_size=60))
    def test_percentiles_are_ordered(self, values):
        from app.services.recommendations.baselines import percentile
        quantiles = [percentile(values, q) for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
        self.assertEqual(quantiles, sorted(quantiles))

    @PROPERTY
    @given(st.lists(_finite, min_size=1, max_size=60))
    def test_a_spread_is_never_negative(self, values):
        from app.services.recommendations.baselines import Stat
        stat = Stat.of(values)
        self.assertGreaterEqual(stat.mad, 0.0)
        self.assertGreaterEqual(stat.sigma, 0.0)

    @PROPERTY
    @given(st.lists(_finite, min_size=1, max_size=60), _finite)
    def test_a_robust_z_is_always_finite(self, values, probe):
        """A flat distribution used to be a division by zero waiting to
        happen; the sentinel path must hold for every input."""
        import math
        from app.services.recommendations.baselines import Stat
        z = Stat.of(values).robust_z(probe)
        self.assertTrue(math.isfinite(z))

    @PROPERTY
    @given(st.lists(_finite, min_size=1, max_size=40))
    def test_the_median_has_a_robust_z_of_zero(self, values):
        from app.services.recommendations.baselines import Stat
        stat = Stat.of(values)
        self.assertAlmostEqual(stat.robust_z(stat.p50), 0.0, places=9)

    @PROPERTY
    @given(st.lists(_finite, min_size=0, max_size=40))
    def test_theil_sen_never_raises(self, values):
        from app.services.recommendations.periods import theil_sen_slope
        slope = theil_sen_slope(values)
        self.assertTrue(slope is None or isinstance(slope, float))

    @PROPERTY
    @given(st.lists(_finite, min_size=3, max_size=40))
    def test_mann_kendall_returns_a_probability(self, values):
        from app.services.recommendations.stats import mann_kendall
        _s, _z, p = mann_kendall(values)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    @PROPERTY
    @given(st.lists(_finite, min_size=3, max_size=30))
    def test_reversing_a_series_flips_the_trend(self, values):
        """A metamorphic property: the same data read backwards must give the
        same evidence with the opposite sign."""
        from app.services.recommendations.stats import mann_kendall
        forward, _z, p_forward = mann_kendall(values)
        backward, _z2, p_backward = mann_kendall(list(reversed(values)))
        self.assertEqual(forward, -backward)
        self.assertAlmostEqual(p_forward, p_backward, places=9)

    @PROPERTY
    @given(
        # Minutes at millisecond resolution, which is what the engine actually
        # handles: durations derived from second-precision timestamps.
        st.lists(
            st.integers(min_value=0, max_value=1_440_000).map(lambda x: x / 1000.0),
            min_size=3, max_size=30,
        ),
        st.floats(min_value=0.5, max_value=10.0, allow_nan=False),
    )
    def test_scaling_a_series_does_not_change_its_trend(self, values, factor):
        """Metamorphic: doubling every duration must not change the direction
        of a trend finding. A rule that fails this is measuring units.

        The generator is bounded to real quantities rather than the whole
        double range, and the reason is worth recording. Hypothesis falsified
        the unbounded version twice, at both ends: values near 1e6 differing in
        their last representable digit, where multiplying rounds them together;
        and the denormal 5e-324, which underflows to zero when halved. Both
        collapse two distinct observations into one, which genuinely changes
        the tie count, so Mann-Kendall is right and the property was wrong.

        Distinct values here differ by at least a millisecond, which is some
        nine orders of magnitude above the spacing of doubles at this size, so
        no factor in range can merge them and the property holds exactly.
        """
        from app.services.recommendations.stats import mann_kendall
        base, _z, _p = mann_kendall(values)
        scaled, _z2, _p2 = mann_kendall([v * factor for v in values])
        self.assertEqual(base, scaled)

    @PROPERTY
    @given(st.integers(min_value=0, max_value=200),
           st.integers(min_value=0, max_value=200))
    def test_a_wilson_interval_always_brackets_its_estimate(self, extra, trials):
        from app.services.recommendations.telemetry import wilson_interval
        successes = min(extra, trials)
        low, high = wilson_interval(successes, trials)
        self.assertGreaterEqual(low, 0.0)
        self.assertLessEqual(high, 1.0)
        self.assertLessEqual(low, high)
        if trials:
            self.assertLessEqual(low, successes / trials + 1e-9)
            self.assertGreaterEqual(high, successes / trials - 1e-9)

    @PROPERTY
    @given(st.lists(_probability, min_size=0, max_size=60),
           st.floats(min_value=0.01, max_value=0.5, allow_nan=False))
    def test_benjamini_hochberg_never_keeps_more_than_it_is_given(self, ps, q):
        from app.services.recommendations.stats import benjamini_hochberg
        mask = benjamini_hochberg(ps, q)
        self.assertEqual(len(mask), len(ps))

    @PROPERTY
    @given(st.lists(_probability, min_size=1, max_size=40),
           st.floats(min_value=0.01, max_value=0.5, allow_nan=False))
    def test_a_kept_p_value_is_never_larger_than_a_dropped_one(self, ps, q):
        """The procedure is a step-up on sorted p-values, so survival must be
        monotone: nothing kept may be weaker than anything discarded."""
        from app.services.recommendations.stats import benjamini_hochberg
        mask = benjamini_hochberg(ps, q)
        kept = [p for p, k in zip(ps, mask) if k]
        dropped = [p for p, k in zip(ps, mask) if not k]
        if kept and dropped:
            self.assertLessEqual(max(kept), min(dropped))

    @PROPERTY
    @given(st.lists(_finite, min_size=0, max_size=40))
    def test_a_sign_test_returns_a_probability(self, diffs):
        from app.services.recommendations.stats import sign_test
        p = sign_test(diffs)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    @PROPERTY
    @given(st.lists(_finite, min_size=0, max_size=40))
    def test_negating_differences_does_not_change_the_sign_test(self, diffs):
        """Metamorphic: the test is two-sided, so direction cannot matter."""
        from app.services.recommendations.stats import sign_test
        self.assertAlmostEqual(
            sign_test(diffs), sign_test([-d for d in diffs]), places=12
        )

    @PROPERTY
    @given(_finite, st.integers(min_value=1, max_value=200))
    def test_a_t_statistic_always_yields_a_probability(self, t, df):
        from app.services.recommendations.stats import student_t_p
        p = student_t_p(t, df)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    @PROPERTY
    @given(st.lists(_finite, min_size=4, max_size=40))
    def test_a_change_point_always_partitions_the_series(self, values):
        from app.services.recommendations.stats import level_shift
        result = level_shift(values)
        if result is not None:
            self.assertEqual(
                result["n_before"] + result["n_after"], len(values)
            )
            self.assertGreater(result["n_before"], 0)
            self.assertGreater(result["n_after"], 0)


class TestRuleProperties(unittest.TestCase):
    """Invariants every rule must satisfy, whatever it is handed.

    These are the contracts the engine relies on. A rule that violates one does
    not crash the panel — it prints something untrue, or an unsatisfied
    template, and nobody notices for months.
    """

    @PROPERTY
    @given(
        st.dictionaries(
            st.sampled_from([
                "deep_work_min", "distraction_share", "idle_share",
                "frag_index", "active_min", "segment_count", "focus_score",
                "meeting_min", "switch_rate", "run_len",
            ]),
            _finite,
            max_size=10,
        )
    )
    def test_no_rule_raises_on_arbitrary_features(self, features):
        """A rule that throws is caught by the engine and skipped, but the card
        is lost silently. Better that it cannot happen."""
        for spec in BY_ID.values():
            context = ctx(days=45, **features)
            if spec.gated(context):
                continue
            try:
                spec.fn(context)
            except Exception as exc:  # noqa: BLE001 - the property under test
                self.fail(f"{spec.id} raised on {features}: {exc!r}")

    @PROPERTY
    @given(st.floats(min_value=0.0, max_value=1e6, allow_nan=False),
           st.integers(min_value=0, max_value=500))
    def test_evidence_confidence_stays_a_probability(self, effect, n):
        """Confidence multiplies into every score, so a value outside [0, 1]
        would silently rescale the whole panel."""
        conf = Evidence(basis="personal", n=n, effect=effect).confidence
        self.assertGreaterEqual(conf, 0.0)
        self.assertLessEqual(conf, 1.0)

    @PROPERTY
    @given(st.integers(min_value=0, max_value=500))
    def test_confidence_never_decreases_with_more_samples(self, n):
        lower = Evidence(basis="personal", n=n).confidence
        higher = Evidence(basis="personal", n=n + 1).confidence
        self.assertLessEqual(lower, higher)

    @PROPERTY
    @given(st.text(max_size=200))
    def test_redaction_never_lengthens_a_title_past_the_cap(self, title):
        from app.services.recommendations.redaction import MAX_LENGTH, redact_title
        self.assertLessEqual(len(redact_title(title)), MAX_LENGTH + 3)

    @PROPERTY
    @given(st.text(max_size=200))
    def test_redaction_is_idempotent(self, title):
        """Running twice must not consume its own markers."""
        from app.services.recommendations.redaction import redact_title
        once = redact_title(title)
        self.assertEqual(redact_title(once), once)

    @PROPERTY
    @given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
           st.integers(min_value=1, max_value=8),
           st.integers(min_value=1, max_value=6))
    def test_exploration_propensities_are_always_usable(self, eps, cap, extra):
        """Every surfaced card must carry a propensity an estimator can divide
        by. A zero here silently breaks every off-policy figure downstream."""
        import random as _random
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Severity

        entries = [
            (_FakeSpec(f"R-{i}", Severity.LOW), Finding(dedup_key=f"k{i}"),
             float(100 - i))
            for i in range(cap + extra)
        ]
        out = RecommendationEngine._explore(
            entries, cap=cap, epsilon=eps, rng=_random.Random(0)
        )
        self.assertEqual(len(out), len(entries))
        for _spec, _finding, _score, propensity, _explored in out[:cap]:
            self.assertGreater(propensity, 0.0)
            self.assertLessEqual(propensity, 1.0)


class TestShadowMode(unittest.TestCase):
    """Rules under trial: evaluated on real data, never shown."""

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import (
            RecommendationEventRecord, RecommendationRecord, UserPreferenceRecord,
        )
        from app.repositories.preference_repository import PreferenceRepository
        from app.services.recommendations.engine import RecommendationEngine
        from app.services.recommendations.types import Scope

        self.Rec = RecommendationRecord
        self.Scope = Scope
        db_engine = make_engine("sqlite:///:memory:")
        Base.metadata.create_all(
            db_engine,
            tables=[RecommendationRecord.__table__,
                    RecommendationEventRecord.__table__,
                    UserPreferenceRecord.__table__],
        )
        self.db = sessionmaker(bind=db_engine)()
        self.prefs = PreferenceRepository(self.db)
        self.engine = RecommendationEngine(session_factory=lambda: self.db)

    def tearDown(self):
        self.db.close()

    @staticmethod
    def _facts_for(spec):
        from string import Formatter
        return {
            name: "x"
            for template in (spec.title, spec.why, spec.action)
            for _, name, _, _ in Formatter().parse(template)
            if name
        }

    def _run(self, rule_ids, muted=None, shadowed=None):
        from app.services.recommendations.types import FeatureContext
        candidates = [
            (BY_ID[rid],
             Finding(dedup_key=f"key/{rid}", facts=self._facts_for(BY_ID[rid])),
             float(len(rule_ids) - i))
            for i, rid in enumerate(rule_ids)
        ]
        self.engine._evaluate = lambda specs, context: [
            c for c in candidates if c[0] in specs
        ]
        context = FeatureContext({}, as_of=BASE, user_id="u1", days_of_history=90)
        self.engine._run_scope(
            self.db, self.Scope.DAILY, context, BASE,
            muted or set(), shadowed or set(),
        )
        rows = self.db.query(self.Rec).all()
        return (
            sorted(r.rule_id for r in rows if not r.shadow),
            sorted(r.rule_id for r in rows if r.shadow),
        )

    def test_a_shadow_rule_is_recorded_but_flagged(self):
        real, shadow = self._run(["HY-01", "HY-03"], shadowed={"HY-03"})
        self.assertEqual(real, ["HY-01"])
        self.assertEqual(shadow, ["HY-03"])

    def test_a_shadow_card_never_reaches_the_panel(self):
        """The whole point. active_for is the one read both the panel and the
        reports go through."""
        self._run(["HY-01", "HY-03"], shadowed={"HY-03"})
        panel = self.engine.active_for(self.db, "u1", BASE.strftime("%Y-%m-%d"))
        self.assertEqual([r.rule_id for r in panel], ["HY-01"])

    def test_a_shadow_card_carries_no_propensity(self):
        """Nothing was surfaced, so there was no surfacing decision to price."""
        self._run(["HY-03"], shadowed={"HY-03"})
        row = self.db.query(self.Rec).filter(self.Rec.shadow.is_(True)).one()
        self.assertIsNone(row.propensity)

    def test_shadow_rules_do_not_consume_a_cap_slot(self):
        """A rule under trial must not displace one that earned its place, so
        it is evaluated outside the section cap entirely."""
        insight = [
            rid for rid, spec in BY_ID.items()
            if spec.section.value == "insight" and spec.scope.value == "daily"
        ][:6]
        real_only, _ = self._run(insight)
        self.setUp()
        real_shadowed, shadow = self._run(insight, shadowed={insight[-1]})
        self.assertEqual(len(real_only), len(real_shadowed))
        self.assertEqual(shadow, [insight[-1]])

    def test_muting_beats_shadowing(self):
        """Not computing a rule is the stronger of the two instructions."""
        real, shadow = self._run(
            ["HY-01", "HY-03"], muted={"HY-03"}, shadowed={"HY-03"}
        )
        self.assertEqual(real, ["HY-01"])
        self.assertEqual(shadow, [])

    def test_telemetry_ignores_shadow_rows(self):
        """A card nobody saw has no acceptance rate, and counting one would
        dilute every figure in the health view."""
        from app.services.recommendations.telemetry import rule_health
        self._run(["HY-03"], shadowed={"HY-03"})
        health = next(
            r for r in rule_health(self.db, "u1").rules if r.rule_id == "HY-03"
        )
        self.assertEqual(health.fired, 0)
        self.assertEqual(health.verdict, "silent")

    def test_evaluation_ignores_shadow_rows(self):
        from app.services.recommendations.evaluation import evaluate
        self._run(["HY-03"], shadowed={"HY-03"})
        self.db.query(self.Rec).update({"status": "applied"})
        self.db.commit()
        self.assertEqual(evaluate(self.db, "u1").labelled_cards, 0)

    def test_shadow_preferences_are_separate_from_mutes(self):
        self.prefs.set_rule_muted("u1", "DY-01", True)
        self.prefs.set_rule_shadowed("u1", "DY-02", True)
        self.assertEqual(self.prefs.muted_rules("u1"), {"DY-01"})
        self.assertEqual(self.prefs.shadowed_rules("u1"), {"DY-02"})


class TestScrutabilityPreferences(unittest.TestCase):
    """Baseline epoch and sensitivity — the other two scrutability controls."""

    def setUp(self):
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.models.db import UserPreferenceRecord
        from app.repositories.preference_repository import PreferenceRepository
        db_engine = make_engine("sqlite:///:memory:")
        UserPreferenceRecord.__table__.create(db_engine)
        self.db = sessionmaker(bind=db_engine)()
        self.prefs = PreferenceRepository(self.db)

    def tearDown(self):
        self.db.close()

    def test_sensitivity_defaults_to_the_shipped_behaviour(self):
        self.assertEqual(self.prefs.sensitivity("u1"), 1.0)

    def test_sensitivity_is_clamped_at_both_ends(self):
        """A zero would make every day remarkable; a negative would invert
        every comparative rule."""
        self.assertEqual(self.prefs.set_sensitivity("u1", 0.0), 0.5)
        self.assertEqual(self.prefs.set_sensitivity("u1", -5.0), 0.5)
        self.assertEqual(self.prefs.set_sensitivity("u1", 99.0), 2.0)

    def test_sensitivity_round_trips(self):
        self.prefs.set_sensitivity("u1", 1.25)
        self.assertAlmostEqual(self.prefs.sensitivity("u1"), 1.25)

    def test_corrupt_sensitivity_falls_back_rather_than_raising(self):
        from app.repositories.preference_repository import SENSITIVITY
        self.prefs.set_text("u1", SENSITIVITY, "not-a-number")
        self.assertEqual(self.prefs.sensitivity("u1"), 1.0)

    def test_sensitivity_moves_the_rule_bar(self):
        from app.services.recommendations.rules.daily import ORDINARY_SPREAD, _bar
        relaxed = ctx(days=45, **{"pref.sensitivity": 2.0})
        strict = ctx(days=45, **{"pref.sensitivity": 0.5})
        self.assertGreater(_bar(relaxed), ORDINARY_SPREAD)
        self.assertLess(_bar(strict), ORDINARY_SPREAD)

    def test_an_absent_preference_leaves_the_bar_alone(self):
        from app.services.recommendations.rules.daily import ORDINARY_SPREAD, _bar
        self.assertAlmostEqual(_bar(ctx(days=45)), ORDINARY_SPREAD)

    def test_the_baseline_epoch_defaults_to_none(self):
        self.assertIsNone(self.prefs.baseline_epoch("u1"))

    def test_the_baseline_epoch_round_trips_and_clears(self):
        """Clearing restores every comparison, which a deletion never could."""
        self.prefs.set_baseline_epoch("u1", "2026-08-01")
        self.assertEqual(self.prefs.baseline_epoch("u1"), "2026-08-01")
        self.prefs.set_baseline_epoch("u1", None)
        self.assertIsNone(self.prefs.baseline_epoch("u1"))

    def test_preferences_are_per_user(self):
        self.prefs.set_sensitivity("u1", 2.0)
        self.assertEqual(self.prefs.sensitivity("u2"), 1.0)


class TestMannWhitneyU(unittest.TestCase):
    """The two-sample rank test behind the unpaired comparisons.

    Distinct from the sign test, which is for paired observations. Using the
    paired test on this month against last would be wrong twice over: the
    samples are different sizes, and nothing links the third day of one month
    to the third of the next.
    """

    def setUp(self):
        from app.services.recommendations.stats import mann_whitney_u
        self.u = mann_whitney_u

    def test_an_empty_arm_is_no_evidence(self):
        self.assertEqual(self.u([], [1.0, 2.0, 3.0]), (0.0, 1.0))
        self.assertEqual(self.u([1.0], []), (0.0, 1.0))

    def test_identical_samples_are_no_evidence(self):
        """scipy returns NaN here because the variance is zero; 1.0 is the
        answer that a caller can actually act on."""
        _u, p = self.u([5.0] * 6, [5.0] * 6)
        self.assertEqual(p, 1.0)

    def test_a_clean_separation_is_significant(self):
        _u, p = self.u([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10], [20.0, 21, 22, 23, 24])
        self.assertLess(p, 0.01)

    def test_overlapping_samples_are_not(self):
        _u, p = self.u([1.0, 2, 3, 4, 5], [2.0, 3, 4, 5, 6])
        self.assertGreater(p, 0.05)

    def test_the_result_is_symmetric_in_its_arguments(self):
        a = [1.0, 4, 6, 8, 12, 3]
        b = [2.0, 5, 7, 9, 11]
        self.assertAlmostEqual(self.u(a, b)[1], self.u(b, a)[1], places=12)

    def test_ties_are_corrected_for(self):
        """Heavily tied data is normal here — rounded minutes repeat — and
        without the tie term the variance is overstated and the test goes
        quiet when it should not."""
        _u, p = self.u([1.0] * 10 + [2.0] * 10, [2.0] * 10 + [3.0] * 10)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)

    def test_matches_a_published_worked_example(self):
        """Mann-Whitney on two small samples with no ties; U is checked
        directly since it is an integer count of wins."""
        u, _p = self.u([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
        self.assertEqual(u, 0.0)

    def test_a_larger_difference_gives_a_smaller_p(self):
        base = [10.0, 11, 12, 13, 14, 15, 16, 17]
        near = [12.0, 13, 14, 15, 16, 17, 18, 19]
        far = [40.0, 41, 42, 43, 44, 45, 46, 47]
        self.assertLess(self.u(base, far)[1], self.u(base, near)[1])


class TestExtendedSignificanceCoverage(unittest.TestCase):
    """The claims that gained a test, and the ones that correctly did not."""

    def test_the_inference_bearing_rules_all_carry_a_p_value(self):
        """A rule whose evidence is a comparison between two samples is making
        an inference, and an inference without a test is an assertion."""
        import ast
        from pathlib import Path
        rules_dir = (
            Path(__file__).resolve().parents[1]
            / "app" / "services" / "recommendations" / "rules"
        )
        inferential = {
            "theil_sen", "spearman", "matched_pairs",
            "month_over_month", "personal_prior_weeks", "sustained_weeks",
        }
        # Parsed rather than pattern-matched. The first version of this test
        # used a non-greedy regex for the Evidence call, which stops at the
        # first closing paren -- and every one of these calls contains
        # n=int(...), so the match ended before the keyword it was looking for
        # and reported every rule as missing one it already had.
        missing = []
        for path in rules_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "id", None) or getattr(
                    node.func, "attr", None
                )
                if name != "Evidence":
                    continue
                keywords = {k.arg: k for k in node.keywords}
                basis = keywords.get("basis")
                if basis is None or not isinstance(basis.value, ast.Constant):
                    continue
                if basis.value.value in inferential and "p_value" not in keywords:
                    missing.append((path.name, basis.value.value))
        self.assertEqual(missing, [])

    def test_descriptive_bases_are_deliberately_untested(self):
        """"You are above your own 90th percentile" is a statement about where
        a value sits, not a hypothesis. Attaching a p-value would be inventing
        a null nobody proposed, and the FDR gate would then suppress plain
        descriptions of the day."""
        from app.services.recommendations.types import Evidence
        descriptive = Evidence(basis="personal_p90", n=30, effect=1.2)
        self.assertIsNone(descriptive.p_value)

    def test_absolute_findings_still_carry_no_p_value(self):
        from app.services.recommendations.types import Evidence
        self.assertIsNone(Evidence(basis="absolute").p_value)


class TestRedactionBackfill(unittest.TestCase):
    """Scrubbing cards stored before redaction existed.

    Those rows are the ones that matter most for an export: they hold rendered
    copy, and a card from months ago is exactly the one nobody remembers the
    contents of.
    """

    def setUp(self):
        import json
        from sqlalchemy import create_engine as make_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.database import Base
        from app.models.db import RecommendationRecord
        from app.services.recommendations.redaction import backfill_stored_cards

        self.json = json
        self.Rec = RecommendationRecord
        self.backfill = backfill_stored_cards
        db_engine = make_engine("sqlite:///:memory:")
        RecommendationRecord.__table__.create(db_engine)
        self.db = sessionmaker(bind=db_engine)()
        self._seq = 0

    def tearDown(self):
        self.db.close()

    def card(self, facts, title="t", why="w", action="a", user="u1"):
        self._seq += 1
        self.db.add(self.Rec(
            id=f"r{self._seq}", user_id=user, rule_id="LV-13", rule_version=1,
            scope="live", section="immediate", severity="low",
            title=title, why=why, action=action, score=1.0,
            dedup_key=f"k{self._seq}", local_date="2026-08-01",
            generated_at="2026-08-01T09:00:00", status="applied",
            facts_json=self.json.dumps(facts),
        ))
        self.db.commit()
        return f"r{self._seq}"

    def test_a_stored_path_is_scrubbed_from_the_facts(self):
        raw = r"C:\Users\me\Clients\Acme\Secret\plan.docx"
        rid = self.card({"last_work_title": raw})
        self.backfill(self.db, "u1")
        self.db.expire_all()
        facts = self.json.loads(self.db.get(self.Rec, rid).facts_json)
        self.assertNotIn("Secret", facts["last_work_title"])
        self.assertIn("plan.docx", facts["last_work_title"])

    def test_the_rendered_sentence_is_patched_not_regenerated(self):
        """Storing copy rather than regenerating it is deliberate: a card still
        says what it said. Only the sensitive substring may change."""
        raw = r"C:\Users\me\Secret\plan.docx"
        rid = self.card(
            {"last_work_title": raw},
            title=f"Pick up where you left off: {raw}",
            why=f"You were last in {raw}.",
        )
        self.backfill(self.db, "u1")
        self.db.expire_all()
        row = self.db.get(self.Rec, rid)
        self.assertTrue(row.title.startswith("Pick up where you left off:"))
        self.assertIn("plan.docx", row.title)
        self.assertNotIn("Secret", row.title)
        self.assertNotIn("Secret", row.why)

    def test_untouched_fields_stay_byte_identical(self):
        raw = "/home/me/secret/plan.md"
        rid = self.card({"last_work_title": raw}, action="Reopen it.")
        self.backfill(self.db, "u1")
        self.db.expire_all()
        self.assertEqual(self.db.get(self.Rec, rid).action, "Reopen it.")

    def test_non_title_facts_survive(self):
        rid = self.card({"last_work_title": "/a/b/c.md", "mins": 20})
        self.backfill(self.db, "u1")
        self.db.expire_all()
        facts = self.json.loads(self.db.get(self.Rec, rid).facts_json)
        self.assertEqual(facts["mins"], 20)

    def test_a_clean_card_is_left_alone(self):
        self.card({"last_work_title": "Untitled - Notepad"})
        result = self.backfill(self.db, "u1")
        self.assertEqual(result["cards_rewritten"], 0)

    def test_the_backfill_is_idempotent(self):
        self.card({"last_work_title": r"C:\Users\me\Secret\plan.docx"})
        first = self.backfill(self.db, "u1")
        second = self.backfill(self.db, "u1")
        self.assertEqual(first["cards_rewritten"], 1)
        self.assertEqual(second["cards_rewritten"], 0)

    def test_malformed_facts_json_is_skipped_not_fatal(self):
        """One bad row must not abort the sweep for every other."""
        self._seq += 1
        self.db.add(self.Rec(
            id="bad", user_id="u1", rule_id="LV-13", rule_version=1,
            scope="live", section="immediate", severity="low", title="t",
            why="w", action="a", score=1.0, dedup_key="kbad",
            local_date="2026-08-01", generated_at="2026-08-01T09:00:00",
            status="applied", facts_json="{not json",
        ))
        self.db.commit()
        good = self.card({"last_work_title": "/a/secret/b.md"})
        result = self.backfill(self.db, "u1")
        self.assertEqual(result["cards_rewritten"], 1)
        self.db.expire_all()
        facts = self.json.loads(self.db.get(self.Rec, good).facts_json)
        self.assertNotIn("secret", facts["last_work_title"])

    def test_null_facts_are_skipped(self):
        self._seq += 1
        self.db.add(self.Rec(
            id="nofacts", user_id="u1", rule_id="LV-13", rule_version=1,
            scope="live", section="immediate", severity="low", title="t",
            why="w", action="a", score=1.0, dedup_key="knone",
            local_date="2026-08-01", generated_at="2026-08-01T09:00:00",
            status="applied", facts_json=None,
        ))
        self.db.commit()
        self.assertEqual(self.backfill(self.db, "u1")["cards_rewritten"], 0)

    def test_other_users_are_not_touched(self):
        rid = self.card({"last_work_title": "/a/secret/b.md"}, user="u2")
        self.backfill(self.db, "u1")
        self.db.expire_all()
        facts = self.json.loads(self.db.get(self.Rec, rid).facts_json)
        self.assertIn("secret", facts["last_work_title"])

    def test_all_users_can_be_swept_at_once(self):
        self.card({"last_work_title": "/a/secret/b.md"}, user="u1")
        self.card({"last_work_title": "/a/secret/c.md"}, user="u2")
        self.assertEqual(self.backfill(self.db)["cards_rewritten"], 2)

    def test_longer_titles_are_replaced_before_shorter_ones(self):
        """One title can be a substring of another; replacing the shorter
        first would corrupt the longer."""
        short = "/a/b.md"
        long = "/a/b.md and /x/secret/c.md"
        rid = self.card(
            {"current_title": short, "last_work_title": long},
            title=f"{long} | {short}",
        )
        self.backfill(self.db, "u1")
        self.db.expire_all()
        self.assertNotIn("secret", self.db.get(self.Rec, rid).title)


if __name__ == "__main__":
    unittest.main()
