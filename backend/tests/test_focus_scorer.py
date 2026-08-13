"""Tests for FocusScorer.

Run from the ``backend`` directory::

    .\\venv\\Scripts\\python.exe -m unittest discover -s tests -v

These pin the properties the previous scorer quietly lost: that the full 0..1
range is reachable, that absence of the user forces zero, that a category can
nudge but never dictate a score, and that whole-session counters are attributed
to the slice a segment actually covers.
"""

import json
import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.time import local_now  # noqa: E402
from app.services.focus_scorer import (  # noqa: E402
    FocusScorer,
    neighbourhood_switch_rates,
)


class FakeSession:
    """Stand-in for OS/IDE/Browser session records — attribute bag only."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


NOW = local_now()


def make_segment(
    duration_sec=900,
    state="active",
    category=None,
    idle_time=0,
    os_session_span_sec=None,
    edit_count=0,
    file_switch_count=0,
    with_ide=False,
    domains=(),
    with_os=True,
):
    """Build a segment dict shaped like the ones ActivitySegmentBuilder produces."""
    end = NOW
    start = end - timedelta(seconds=duration_sec)

    # An OS session may run longer than the segment that slices it; span lets a
    # test exercise the proration path.
    span = os_session_span_sec or duration_sec
    os_start = end - timedelta(seconds=span)

    os_sessions = []
    if with_os:
        os_sessions.append(
            FakeSession(
                id="os-1",
                app_name="Code.exe",
                state=state,
                idle_time=idle_time,
                process_id=101,
                session_start=os_start.isoformat(),
                session_end=end.isoformat(),
            )
        )

    ide_sessions = []
    if with_ide:
        ide_sessions.append(
            FakeSession(
                id="ide-1",
                ide_name="vscode",
                workspace_name="smartdesk",
                active_file_name="focus_scorer.py",
                edit_count=edit_count,
                file_switch_count=file_switch_count,
                process_id=202,
                session_start=start.isoformat(),
                session_end=end.isoformat(),
            )
        )

    browser_sessions = [
        FakeSession(
            id=f"br-{index}",
            browser_name="chrome",
            domain=domain,
            url=f"https://{domain}/",
            process_id=303,
            session_start=start.isoformat(),
            session_end=end.isoformat(),
        )
        for index, domain in enumerate(domains)
    ]

    return {
        "start_time": start,
        "end_time": end,
        "duration": float(duration_sec),
        "state": state,
        "category": category,
        "primary_source": "ide" if with_ide else "os",
        "sources": {"os": os_sessions, "ide": ide_sessions, "browser": browser_sessions},
        "text_content": {"app_name": "Code.exe", "title": "t", "detail": ""},
    }


def score(**kwargs):
    return FocusScorer().score_segment(make_segment(**kwargs))[0]


class RangeIsReachable(unittest.TestCase):
    """The old scorer could not produce a score above ~0.5 on real data."""

    def test_a_perfect_work_segment_reaches_exactly_one(self):
        self.assertEqual(score(duration_sec=900, category="work"), 1.0)

    def test_editing_is_an_alternative_route_to_the_top(self):
        self.assertEqual(
            score(duration_sec=900, category="system", with_ide=True, edit_count=100),
            1.0,
        )

    def test_a_neutral_category_still_scores_high(self):
        # Nothing but 'work' used to be able to approach even 0.7, because the
        # category multiplier scaled the whole result. A perfectly measured
        # segment now earns the full base regardless of what it was.
        self.assertAlmostEqual(
            score(duration_sec=900, category="system"),
            FocusScorer.BASE_SCALE,
            places=9,
        )

    def test_bottom_is_reachable(self):
        self.assertEqual(score(state="locked"), 0.0)

    def test_every_score_stays_in_bounds(self):
        for category in list(FocusScorer.CATEGORY_ADJUSTMENTS) + [None, "nonsense"]:
            for duration in (5, 60, 300, 900):
                for state in ("active", "idle", "locked"):
                    value = score(duration_sec=duration, state=state, category=category)
                    self.assertGreaterEqual(value, 0.0)
                    self.assertLessEqual(value, 1.0)


class PresenceGatesTheScore(unittest.TestCase):
    def test_locked_is_zero(self):
        self.assertEqual(score(state="locked", duration_sec=900, category="work"), 0.0)

    def test_idle_is_zero(self):
        self.assertEqual(score(state="idle", idle_time=900, duration_sec=900), 0.0)

    def test_idle_without_logged_idle_seconds_is_still_zero(self):
        # 18 of 642 recorded idle sessions carry idle_time=0. State wins there.
        self.assertEqual(score(state="idle", idle_time=0, duration_sec=900), 0.0)

    def test_a_stale_overlapping_session_cannot_revive_an_idle_segment(self):
        # Some segments overlap both the real 300s 'idle' session and a stale
        # 11-hour 'active' one left open by a crashed collector. Summing idle
        # across every overlapping session double-counted wall-clock and lifted
        # genuinely idle stretches back to 0.56.
        segment = make_segment(duration_sec=180, state="idle", idle_time=119)
        segment["sources"]["os"].insert(
            0,
            FakeSession(
                id="os-stale",
                app_name="Code",
                state="active",
                idle_time=0,
                process_id=1,
                session_start=(NOW - timedelta(seconds=39163)).isoformat(),
                session_end=NOW.isoformat(),
            ),
        )
        self.assertEqual(FocusScorer().score_segment(segment)[0], 0.0)

    def test_half_idle_scores_below_fully_active(self):
        half = score(duration_sec=900, idle_time=450)
        full = score(duration_sec=900, idle_time=0)
        self.assertLess(half, full)
        self.assertGreater(half, 0.0)


class CategoryIsAnAdjustmentNotAGate(unittest.TestCase):
    def test_entertainment_does_not_annihilate_a_real_measurement(self):
        # The old coefficient of -1.0 produced a multiplier of exactly 0.0, so
        # every entertainment segment scored 0 regardless of its signals.
        self.assertGreater(score(duration_sec=900, category="entertainment"), 0.0)

    def test_unknown_category_is_neutral(self):
        # Previously an unrecognised category fell to a 0.5 multiplier, making a
        # categorizer miss indistinguishable from a mediocre session.
        self.assertEqual(
            score(duration_sec=300, category=None),
            score(duration_sec=300, category="other"),
        )

    def test_adjustment_is_bounded(self):
        neutral = score(duration_sec=300, category="other")
        for category, adjustment in FocusScorer.CATEGORY_ADJUSTMENTS.items():
            shifted = score(duration_sec=300, category=category)
            self.assertAlmostEqual(shifted, max(0.0, min(1.0, neutral + adjustment)), places=9)


class SignalsAreMonotone(unittest.TestCase):
    def test_longer_uninterrupted_segments_score_higher(self):
        scores = [score(duration_sec=d) for d in (30, 120, 300, 600)]
        self.assertEqual(scores, sorted(scores))
        self.assertLess(scores[0], scores[-1])

    def test_more_file_switching_scores_lower(self):
        calm = score(duration_sec=600, with_ide=True, file_switch_count=0)
        busy = score(duration_sec=600, with_ide=True, file_switch_count=60)
        self.assertLess(busy, calm)

    def test_more_domains_scores_lower(self):
        one = score(duration_sec=600, domains=("docs.python.org",))
        many = score(duration_sec=600, domains=tuple(f"site{i}.com" for i in range(12)))
        self.assertLess(many, one)

    def test_a_single_domain_is_not_charged_a_switch(self):
        # The old scorer added len(domains) rather than len(domains) - 1.
        self.assertEqual(
            score(duration_sec=600, domains=("docs.python.org",)),
            score(duration_sec=600, domains=()),
        )


class EditingIsABonusNeverAPenalty(unittest.TestCase):
    def test_an_ide_session_without_edits_is_not_punished(self):
        # 85% of segments have no IDE session at all; instrumented-but-quiet
        # must not score below uninstrumented.
        self.assertEqual(
            score(duration_sec=600, with_ide=True, edit_count=0),
            score(duration_sec=600, with_ide=False),
        )

    def test_dense_editing_raises_the_score(self):
        # Kept below the ceiling deliberately: a long work segment already
        # reaches 1.0 on measurement alone, where the bonus has nowhere to go.
        quiet = score(duration_sec=120, with_ide=True, edit_count=0)
        busy = score(duration_sec=120, with_ide=True, edit_count=40)
        self.assertGreater(busy, quiet)

    def test_the_bonus_is_capped(self):
        plenty = score(duration_sec=120, with_ide=True, edit_count=40)
        absurd = score(duration_sec=120, with_ide=True, edit_count=4000)
        self.assertEqual(plenty, absurd)


class WholeSessionCountersAreProrated(unittest.TestCase):
    def test_idle_time_is_attributed_to_the_slice_the_segment_covers(self):
        # A 1-hour OS session idle for 30 min, sliced into a 5-minute segment:
        # the segment inherits half the idle, not all of it. The old scorer
        # compared the session's full 1800s idle against 300s of duration and
        # concluded the user was completely absent.
        components = FocusScorer().components(
            make_segment(duration_sec=300, os_session_span_sec=3600, idle_time=1800)
        )
        self.assertAlmostEqual(components["active"], 0.5, places=2)

    def test_edit_count_is_prorated_the_same_way(self):
        segment = make_segment(duration_sec=600, with_ide=True, edit_count=40)
        segment["sources"]["ide"][0].session_start = (
            NOW - timedelta(seconds=1200)
        ).isoformat()
        components = FocusScorer().components(segment)
        # 40 edits over 20 min, half of which this 10-min segment covers -> 2/min.
        self.assertAlmostEqual(components["edits_per_min"], 2.0, places=2)


class NeighbourhoodSwitchRates(unittest.TestCase):
    """The timeline signal that replaced the near-useless in-segment count."""

    @staticmethod
    def timeline(apps, each_sec=60):
        """Build a back-to-back timeline of equal-length segments."""
        entries = []
        cursor = NOW - timedelta(seconds=each_sec * len(apps))
        for app in apps:
            entries.append((cursor, cursor + timedelta(seconds=each_sec), app))
            cursor += timedelta(seconds=each_sec)
        return entries

    def test_a_single_app_throughout_has_no_switches(self):
        rates = neighbourhood_switch_rates(self.timeline(["Code"] * 10))
        self.assertEqual(set(rates), {0.0})

    def test_alternating_apps_produce_a_high_rate(self):
        rates = neighbourhood_switch_rates(self.timeline(["Code", "Chrome"] * 5))
        self.assertTrue(all(r > 0 for r in rates))
        self.assertGreater(max(rates), 0.5)

    def test_splits_within_one_app_are_not_counted(self):
        # The splitter also cuts at IDE/browser session edges and the 900s cap.
        # Those boundaries must not read as attention moving.
        same = neighbourhood_switch_rates(self.timeline(["Code"] * 8))
        self.assertEqual(max(same), 0.0)

    def test_result_is_aligned_to_input_order_not_sorted_order(self):
        entries = self.timeline(["Code", "Chrome", "Code"])
        shuffled = [entries[2], entries[0], entries[1]]
        rates = neighbourhood_switch_rates(shuffled)
        by_start = {entry[0]: rate for entry, rate in zip(shuffled, rates)}
        ordered = neighbourhood_switch_rates(entries)
        for entry, rate in zip(entries, ordered):
            self.assertAlmostEqual(by_start[entry[0]], rate, places=9)

    def test_empty_timeline_is_handled(self):
        self.assertEqual(neighbourhood_switch_rates([]), [])


class NeighbourhoodOverridesInSegmentCount(unittest.TestCase):
    def test_supplied_rate_wins_over_the_in_segment_fallback(self):
        segment = make_segment(duration_sec=600, with_ide=True, file_switch_count=0)
        calm = FocusScorer().components(segment)
        self.assertEqual(calm["switches_per_min"], 0.0)

        segment[FocusScorer.NEIGHBOURHOOD_KEY] = 9.0
        busy = FocusScorer().components(segment)
        self.assertEqual(busy["switches_per_min"], 9.0)
        self.assertLess(busy["churn"], calm["churn"])

    def test_the_fallback_still_works_without_a_supplied_rate(self):
        # Callers that score a lone segment have no timeline to consult.
        segment = make_segment(duration_sec=600, with_ide=True, file_switch_count=60)
        self.assertGreater(FocusScorer().components(segment)["switches_per_min"], 0.0)

    def test_the_source_is_recorded_in_the_audit_trail(self):
        scorer = FocusScorer()
        plain = json.loads(scorer.score_segment(make_segment())[2])
        self.assertEqual(plain["switch_source"], "in_segment")

        segment = make_segment()
        segment[FocusScorer.NEIGHBOURHOOD_KEY] = 3.0
        supplied = json.loads(scorer.score_segment(segment)[2])
        self.assertEqual(supplied["switch_source"], "neighbourhood")


class TheSustainedFloorRampsIn(unittest.TestCase):
    def test_a_five_second_glance_no_longer_inherits_the_full_floor(self):
        # Granted flat, the floor handed 0.263 to 5-second segments and put 496
        # sub-minute segments above 0.6.
        self.assertLess(FocusScorer()._sustained(5.0), 0.05)

    def test_the_floor_is_fully_earned_by_one_minute(self):
        scorer = FocusScorer()
        at_ramp_end = scorer._sustained(scorer.FLOOR_RAMP_SEC)
        expected_floor = scorer.SUSTAINED_FLOOR
        reached = scorer.FLOOR_RAMP_SEC / scorer.SUSTAINED_FULL_SEC
        self.assertAlmostEqual(
            at_ramp_end, expected_floor + (1 - expected_floor) * reached, places=9
        )

    def test_sustained_is_still_monotone_across_the_ramp(self):
        scorer = FocusScorer()
        values = [scorer._sustained(d) for d in (1, 5, 15, 30, 60, 120, 300, 900)]
        self.assertEqual(values, sorted(values))


class ContradictoryIdleCounterIsDistrusted(unittest.TestCase):
    def test_an_active_session_claiming_total_idle_is_not_zeroed(self):
        # 56 real segments looked like this, including 12.5 uninterrupted minutes
        # in DB Browser for SQLite that scored 0.0.
        segment = make_segment(duration_sec=753, state="active", idle_time=753)
        self.assertGreater(FocusScorer().score_segment(segment)[0], 0.5)

    def test_a_believable_idle_count_is_still_applied(self):
        partial = FocusScorer().components(
            make_segment(duration_sec=900, state="active", idle_time=450)
        )
        self.assertAlmostEqual(partial["active"], 0.5, places=2)


class PersistedSignalsRoundTrip(unittest.TestCase):
    def test_stored_components_reproduce_the_stored_score(self):
        scorer = FocusScorer()
        segment = make_segment(duration_sec=420, category="work", with_ide=True, edit_count=12)
        expected, _concurrent, signals_json = scorer.score_segment(segment)

        recovered = scorer.components_from_signals_json(signals_json)
        self.assertTrue(recovered, "components must survive the JSON round trip")
        self.assertAlmostEqual(
            scorer.score_from_components(recovered, "work"), expected, places=9
        )

    def test_unreadable_signals_yield_nothing_rather_than_invented_defaults(self):
        scorer = FocusScorer()
        for bad in (None, "", "not json", "[]", '{"raw_signals": {"active_ratio": 0.8}}'):
            self.assertEqual(scorer.components_from_signals_json(bad), {})


if __name__ == "__main__":
    unittest.main()
