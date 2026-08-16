"""Tests for ActivitySegmentBuilder's scheduling and scoring wiring.

Run from the ``backend`` directory::

    .\\venv\\Scripts\\python.exe -m unittest discover -s tests -v

These pin the things that were silently broken rather than the happy path. The
builder carried two definitions of ``start``, ``stop``, ``_schedule`` and
``_tick``; Python kept the second of each, so the watermark catch-up logic was
unreachable and every tick lost 60 seconds of timeline to a doubly-applied
arrival delay. Nothing failed loudly — the holes only showed up by querying
coverage. Hence the assertions below about *which* method a tick reaches.
"""

import sys
import unittest
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.time import local_now  # noqa: E402
from app.services import activity_segment_builder as builder_module  # noqa: E402
from app.services.activity_segment_builder import (  # noqa: E402
    BUILD_INTERVAL_SEC,
    MAX_CATCHUP_SPAN_SEC,
    ActivitySegmentBuilder,
)
from app.services.focus_scorer import FocusScorer  # noqa: E402


class NoShadowedDefinitions(unittest.TestCase):
    """A duplicate `def` is invisible at runtime, so assert the survivors directly."""

    def test_each_scheduling_method_is_defined_exactly_once(self):
        source = Path(builder_module.__file__).read_text(encoding="utf-8")
        for name in ("start", "stop", "_schedule", "_tick"):
            count = source.count(f"\n    def {name}(")
            self.assertEqual(
                count, 1, f"{name} is defined {count} times; a duplicate silently wins"
            )

    def test_a_tick_reaches_the_watermark_path(self):
        # The discarded _tick called _build_recent_segments (watermark-based);
        # the surviving one called _process (fixed now-minus-interval window).
        # This is the assertion that would have caught the shadowing.
        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        calls = []
        instance._build_recent_segments = lambda: calls.append("watermark")
        instance._schedule = lambda: None
        instance._tick()
        self.assertEqual(calls, ["watermark"])

    def test_the_superseded_fixed_window_builder_is_gone(self):
        self.assertFalse(
            hasattr(ActivitySegmentBuilder, "_process"),
            "_process applied the arrival delay twice; it should not have survived",
        )


class StartPreservesConstructedIdentity(unittest.TestCase):
    def test_bare_start_keeps_the_user_and_device_from_init(self):
        # The shadowing definition defaulted to user_id="local_user", device_id="",
        # so main.py's bare start() discarded settings.DEFAULT_USER_ID entirely.
        instance = ActivitySegmentBuilder(user_id="alice", device_id="workstation")
        instance._schedule = lambda: None
        instance.start()
        try:
            self.assertEqual(instance._user_id, "alice")
            self.assertEqual(instance._device_id, "workstation")
            self.assertEqual(instance._interval_seconds, BUILD_INTERVAL_SEC)
        finally:
            instance.stop()

    def test_explicit_arguments_still_override(self):
        instance = ActivitySegmentBuilder(user_id="alice", device_id="workstation")
        instance._schedule = lambda: None
        instance.start(user_id="bob", device_id="laptop", interval_seconds=60)
        try:
            self.assertEqual(instance._user_id, "bob")
            self.assertEqual(instance._device_id, "laptop")
            self.assertEqual(instance._interval_seconds, 60)
        finally:
            instance.stop()

    def test_interval_is_usable_before_start(self):
        # run_once and _schedule both read _interval_seconds; it used to be set
        # only by the shadowing start(), so touching it first raised AttributeError.
        self.assertEqual(
            ActivitySegmentBuilder(device_id="d")._interval_seconds, BUILD_INTERVAL_SEC
        )


class FakeQuery:
    """Stand-in for the SQLAlchemy chains the builder walks.

    Supports both terminals the builder uses: ``scalar()`` for the watermark
    lookup and ``all()`` for the neighbourhood context rows. Omitting ``all()``
    made the context tests below pass by falling into the exception handler,
    which would have stayed green with context loading entirely broken.
    """

    def __init__(self, scalar_result=None, rows=()):
        self._scalar_result = scalar_result
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def scalar(self):
        return self._scalar_result

    def all(self):
        return list(self._rows)


class FakeDb:
    def __init__(self, scalar_result=None, rows=()):
        self._scalar_result = scalar_result
        self._rows = rows

    def query(self, *_a, **_k):
        return FakeQuery(self._scalar_result, self._rows)


class WatermarkResumption(unittest.TestCase):
    def setUp(self):
        self.builder = ActivitySegmentBuilder(user_id="u", device_id="d")
        self.now = local_now()

    def test_cold_start_falls_back_to_one_interval(self):
        resolved = self.builder._resolve_watermark(FakeDb(None), self.now)
        self.assertAlmostEqual(
            (self.now - resolved).total_seconds(), BUILD_INTERVAL_SEC, delta=1
        )

    def test_it_resumes_from_the_last_covered_instant(self):
        # This is what heals the holes: the next window starts where the last
        # segment ended, not at now-minus-interval.
        last_end = self.now - timedelta(seconds=1800)
        resolved = self.builder._resolve_watermark(FakeDb(last_end), self.now)
        self.assertEqual(resolved, last_end)

    def test_catch_up_is_bounded(self):
        ancient = self.now - timedelta(days=30)
        resolved = self.builder._resolve_watermark(FakeDb(ancient), self.now)
        self.assertAlmostEqual(
            (self.now - resolved).total_seconds(), MAX_CATCHUP_SPAN_SEC, delta=1
        )


class NeighbourhoodSwitchesAreAttached(unittest.TestCase):
    """The signal must actually reach seg_dict — `state` went missing this way."""

    def make_segments(self, apps, each_sec=60):
        segments = []
        cursor = local_now() - timedelta(seconds=each_sec * len(apps))
        for app in apps:
            segments.append({
                "start_time": cursor,
                "end_time": cursor + timedelta(seconds=each_sec),
                "duration": float(each_sec),
                "text_content": {"app_name": app, "title": "t", "detail": ""},
            })
            cursor += timedelta(seconds=each_sec)
        return segments

    def test_every_segment_receives_a_rate(self):
        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        segments = self.make_segments(["Code", "Chrome", "Code", "Chrome"])
        instance._attach_neighbourhood_switches(FakeDb(rows=[]), "u", "d", segments)
        for segment in segments:
            self.assertIn(FocusScorer.NEIGHBOURHOOD_KEY, segment)
            self.assertGreater(segment[FocusScorer.NEIGHBOURHOOD_KEY], 0.0)

    def test_a_single_app_run_reports_no_switching(self):
        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        segments = self.make_segments(["Code"] * 5)
        instance._attach_neighbourhood_switches(FakeDb(rows=[]), "u", "d", segments)
        for segment in segments:
            self.assertEqual(segment[FocusScorer.NEIGHBOURHOOD_KEY], 0.0)

    def test_persisted_context_raises_the_rate_for_a_calm_tick(self):
        # The point of the lookback: a tick holding only one app still sees the
        # churn that happened just before its window. Without the context rows
        # the first segments of every tick look artificially focused.
        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        segments = self.make_segments(["Code", "Code"])
        earlier = segments[0]["start_time"]
        context = [
            (earlier - timedelta(seconds=60 * (i + 1)),
             earlier - timedelta(seconds=60 * i),
             "Chrome" if i % 2 else "Slack")
            for i in range(1, 5)
        ]

        without = self.make_segments(["Code", "Code"])
        instance._attach_neighbourhood_switches(FakeDb(rows=[]), "u", "d", without)
        instance._attach_neighbourhood_switches(FakeDb(rows=context), "u", "d", segments)

        self.assertEqual(without[0][FocusScorer.NEIGHBOURHOOD_KEY], 0.0)
        self.assertGreater(segments[0][FocusScorer.NEIGHBOURHOOD_KEY], 0.0)

    def test_a_failing_context_query_does_not_break_the_build(self):
        class ExplodingDb:
            def query(self, *_a, **_k):
                raise RuntimeError("database is locked")

        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        segments = self.make_segments(["Code", "Chrome"])
        instance._attach_neighbourhood_switches(ExplodingDb(), "u", "d", segments)
        for segment in segments:
            self.assertIn(FocusScorer.NEIGHBOURHOOD_KEY, segment)

    def test_no_segments_is_handled(self):
        instance = ActivitySegmentBuilder(user_id="u", device_id="d")
        instance._attach_neighbourhood_switches(FakeDb(rows=[]), "u", "d", [])


if __name__ == "__main__":
    unittest.main()
