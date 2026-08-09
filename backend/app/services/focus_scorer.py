"""Focus scoring service.

Turns one activity segment into a 0..1 focus score.

The score answers a narrow question — how much of this segment was sustained,
uninterrupted presence on one thing — and nothing wider. It is deliberately not
a productivity verdict: *what* the user was doing enters as a small bounded
adjustment, never as a gate.

Shape::

    base  = 0.90 x active x (0.50 x sustained + 0.50 x churn)
    score = clamp(base + category_adjustment + edit_bonus, 0, 1)

Three measured signals, two bounded adjustments. Every constant below is set
from the recorded population rather than from a guess about how someone works —
the first draft of this file saturated its editing signal at 12 edits/minute
when the busiest session ever recorded managed 4.8, so the bonus was unreachable
and no segment could score 1.0. Every signal is derivable for
every segment, and every one reaches both 0.0 and 1.0 on real data — which the
previous five-component version did not. Measured over the 4,307 scorable
segments recorded up to 2026-08-09, four independent leaks held observed scores
near 0.5, none of them describing the user's focus:

* ``length_score`` plateaued at 20-90 minutes while ``MAX_SEGMENT_SEC`` cuts
  every segment at 15, so it was capped at 0.75 and its decay branch was dead.
* ``edit_density`` was a flat zero for the 85% of segments with no IDE session,
  charging them 0.20 for missing instrumentation rather than missing focus.
* ``switch_rate`` was forced to 0.5 whenever it computed to zero, so a segment
  that never left one app could not earn the full switch score. Measuring it
  inside the segment was the deeper mistake — the splitter cuts on every app
  change, so the boundaries *are* the switches and 74.5% of segments reported
  none at all. Switching is now measured over the surrounding timeline; see
  :func:`neighbourhood_switch_rates`.
* the category multiplier ``0.5 + 0.5 * coefficient`` scaled the entire result:
  70% of segments sat at a multiplier of 0.7 or less, and 'entertainment' forced
  an exact 0.0 no matter what the signals said.

All four are gone. Component math lives in exactly one place (:meth:`components`
and :meth:`score_from_components`) so the persisted explainability trail in
``signals_json`` cannot drift from the score it claims to explain.
"""

import bisect
import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.time import parse_iso

# Width of the window used to measure switching around a segment. Ten minutes is
# long enough to contain several segments — the median is 65 seconds — so the
# count actually varies, and short enough that it still describes *this* stretch
# of the day rather than the whole morning.
NEIGHBOURHOOD_WINDOW_SEC: float = 600.0


def neighbourhood_switch_rates(
    timeline: list[tuple[datetime, datetime, Any]],
    window_sec: float = NEIGHBOURHOOD_WINDOW_SEC,
) -> list[float]:
    """Switches per minute around each entry of a segment timeline.

    ``timeline`` is ``(start, end, app_name)`` per segment, in any order; the
    result is aligned to the input order. Only boundaries where the app actually
    *changes* are counted — ``ActivitySegmentBuilder._split_at_boundaries`` also
    cuts on IDE/browser session edges and at the 900s cap, and those splits mean
    no attention moved.

    Lives here, next to the scorer that consumes it, so ActivitySegmentBuilder
    and scripts/backfill_focus_scores.py share one definition instead of drifting
    apart with two.
    """
    if not timeline:
        return []

    order = sorted(range(len(timeline)), key=lambda i: timeline[i][0])

    # Instants where the foreground app changed between adjacent segments.
    boundaries: list[datetime] = []
    for previous, current in zip(order, order[1:]):
        if timeline[previous][2] != timeline[current][2]:
            boundaries.append(timeline[current][0])

    window_min = window_sec / 60.0
    half = window_sec / 2.0
    rates = [0.0] * len(timeline)
    for index in order:
        start, end, _app = timeline[index]
        midpoint = start + (end - start) / 2
        low = midpoint - timedelta(seconds=half)
        high = midpoint + timedelta(seconds=half)
        count = bisect.bisect_right(boundaries, high) - bisect.bisect_left(boundaries, low)
        rates[index] = count / window_min
    return rates


class FocusScorer:
    """Scores a single activity segment on sustained, uninterrupted attention."""

    # Bumped whenever the formula changes, so a stored signals_json can be told
    # apart from one written by a different version of this file.
    SIGNALS_VERSION = 2

    # Unbroken seconds on one thing that count as fully sustained. Segments are
    # cut at MAX_SEGMENT_SEC (900s), so this has to sit below that or the signal
    # saturates nowhere — the mistake the old 20-90 minute plateau made. Five
    # minutes is half the cap and lands where sustained attention actually
    # shows up in the data: 63% of segments past five minutes belong to a
    # single-app run of ten minutes or more, against 7% of sub-minute ones.
    SUSTAINED_FULL_SEC = 300.0

    # A segment boundary is not always an attention break. The splitter also
    # cuts at IDE and browser session edges and at the 900s cap, so one unbroken
    # stretch arrives as several rows — measured across the recorded history the
    # contiguous same-app run behind a segment is about twice the segment's own
    # length. This floor credits that baseline continuity instead of scoring a
    # chopped-up focus block as though the user had bounced between windows.
    SUSTAINED_FLOOR = 0.25

    # Seconds over which SUSTAINED_FLOOR is phased in. A segment shorter than
    # this is too brief to be a fragment of anything, so it earns only part of
    # the floor. One minute is the point past which the recorded contiguous-run
    # data starts supporting the fragment argument at all.
    FLOOR_RAMP_SEC = 60.0

    # Key a producer sets on the segment dict to supply the switch rate measured
    # over the surrounding timeline. See _switches_per_min for why the in-segment
    # count cannot carry this signal on its own.
    NEIGHBOURHOOD_KEY = "neighbourhood_switches_per_min"

    # Switches per minute at which churn decays to 1/e, fitted to the observed
    # neighbourhood rates: median 0.50/min, p90 2.10, busiest stretch 4.70. At
    # this value that range maps onto churn 1.00 down to 0.21, so an app change
    # every 29 seconds reads as half-broken focus and one every 13 seconds as
    # mostly broken. Raising it to 6.0 — which is what I guessed before measuring
    # — compresses the entire observed range into 0.46..1.00 and wastes most of
    # the signal's resolution.
    SWITCH_TOLERANCE = 3.0

    # How much of a session's overlap prorated idle_time must claim before the
    # counter is treated as broken rather than believed. See _active_ratio.
    IDLE_COUNTER_SANITY = 0.99

    # Edits per minute earning the full editing bonus. Set from the observed
    # spread across IDE sessions with any editing at all: median 0.74/min,
    # p75 1.11, p95 3.43, busiest ever 4.80. Sitting between p75 and p95 means
    # ordinary editing earns most of the bonus and a heavy session earns it all.
    EDIT_SATURATION = 1.5
    EDIT_BONUS_MAX = 0.10

    SUSTAINED_WEIGHT = 0.50
    CHURN_WEIGHT = 0.50

    # Share of the score the measured signals own outright. A flawless
    # measurement earns 0.90 by itself, and either adjustment can carry it to a
    # full 1.0 — so a perfect score is reachable without demanding that every
    # optional signal line up at once, while still requiring the measurement to
    # be perfect first. At the ceiling the two adjustments overlap and clamp;
    # that is intended, they are alternative routes to the top rather than a
    # checklist.
    BASE_SCALE = 0.90

    # Additive, applied once, bounded. A category can nudge a score but can
    # never manufacture or erase one — the measurement stays visible underneath.
    # Anything unrecognised, None included, is neutral: the categorizer being
    # unsure is not evidence about focus. Keys track Categorizer.PERSISTABLE_CATEGORIES.
    CATEGORY_ADJUSTMENTS = {
        "work": 0.10,
        "learn": 0.05,
        "meetings": 0.0,
        "system": 0.0,
        "other": 0.0,
        "communication": -0.05,
        "social_media": -0.10,
        "entertainment": -0.10,
    }

    def __init__(self) -> None:
        # Memoises parsed session timestamps for the life of this instance; see
        # _session_bounds. Callers build one scorer per batch, so it is bounded by
        # the batch rather than growing for the process lifetime.
        self._bounds_cache: dict[tuple, tuple] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def score_segment(self, segment: dict[str, Any]) -> tuple[float, str, str]:
        """Score a segment and produce the JSON metadata persisted alongside it.

        Returns:
            ``(focus_score, concurrent_json, signals_json)``
        """
        category = segment.get("category")
        components = self.components(segment)
        score = self.score_from_components(components, category)

        concurrent_json = json.dumps(
            self._build_concurrency_log(segment), ensure_ascii=False
        )
        signals_json = json.dumps(
            {
                # Flat, and keyed exactly as score_from_components consumes it,
                # so a stored trail replays into the score it sits next to. The
                # old shape nested everything under "raw_signals"/"component_scores",
                # which this module's own reader could not parse — it silently
                # fell through to hardcoded defaults on every call.
                "version": self.SIGNALS_VERSION,
                "components": components,
                "weights": {
                    "base_scale": self.BASE_SCALE,
                    "sustained": self.SUSTAINED_WEIGHT,
                    "churn": self.CHURN_WEIGHT,
                },
                "category": category,
                "category_adjustment": self.CATEGORY_ADJUSTMENTS.get(category, 0.0),
                "edit_bonus": self._edit_bonus(components),
                # Which producer supplied the switch rate. Worth persisting: a
                # table full of "in_segment" means a producer stopped populating
                # the timeline signal and the score quietly lost its main
                # discriminator, which is invisible from the score alone.
                "switch_source": (
                    "neighbourhood"
                    if segment.get(self.NEIGHBOURHOOD_KEY) is not None
                    else "in_segment"
                ),
                "score": score,
                "computed_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        return score, concurrent_json, signals_json

    def components(self, segment: dict[str, Any]) -> dict[str, float]:
        """Derive the measured signals for a segment. The only place they are computed."""
        duration = max(0.0, float(segment.get("duration", 0.0)))
        duration_min = duration / 60.0
        state = segment.get("state")

        switches_per_min = self._switches_per_min(segment, duration_min)
        return {
            "active": self._active_ratio(segment, duration, state),
            "sustained": self._sustained(duration),
            "churn": math.exp(-switches_per_min / self.SWITCH_TOLERANCE),
            "switches_per_min": switches_per_min,
            "edits_per_min": self._edits_per_min(segment, duration_min),
        }

    def _sustained(self, duration: float) -> float:
        """How much unbroken time this segment represents.

        The floor is phased in over ``FLOOR_RAMP_SEC`` rather than granted flat.
        Its justification — that the splitter fragments one real focus block into
        several rows — only holds for a segment long enough to plausibly *be* a
        fragment. Granted flat it handed 0.263 to five-second glances, which is
        how 496 sub-minute segments came to score above 0.6.
        """
        if duration <= 0:
            return 0.0
        floor = self.SUSTAINED_FLOOR * min(duration / self.FLOOR_RAMP_SEC, 1.0)
        reached = min(duration / self.SUSTAINED_FULL_SEC, 1.0)
        return floor + (1.0 - floor) * reached

    def score_from_components(
        self,
        components: dict[str, float],
        category: str | None = None,
    ) -> float:
        """Combine measured components into the final 0..1 score."""
        active = components.get("active", 0.0)

        # Presence gates everything. If the machine says nobody was there, no
        # amount of tidiness elsewhere makes it focus, and neither adjustment
        # below can lift it off zero.
        if active <= 0.0:
            return 0.0

        base = self.BASE_SCALE * active * (
            self.SUSTAINED_WEIGHT * components.get("sustained", 0.0)
            + self.CHURN_WEIGHT * components.get("churn", 0.0)
        )
        adjusted = (
            base
            + self.CATEGORY_ADJUSTMENTS.get(category, 0.0)
            + self._edit_bonus(components)
        )
        return max(0.0, min(1.0, adjusted))

    def components_from_signals_json(self, signals_json: str | None) -> dict[str, float]:
        """Recover persisted components from ``signals_json``.

        Replaces ``create_signals_from_segment``, which claimed to do this but
        read the top level of a nested document with an ``isinstance(v, (int, float))``
        filter — every value there was a dict or a string, so it returned ``{}``
        and substituted invented defaults on every call.

        Returns an empty dict when nothing usable is stored; callers should
        rescore from source rather than trusting a fabricated fallback.
        """
        if not signals_json:
            return {}
        try:
            document = json.loads(signals_json)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}
        if not isinstance(document, dict):
            return {}
        components = document.get("components")
        if not isinstance(components, dict):
            return {}
        return {
            key: float(value)
            for key, value in components.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }

    # ------------------------------------------------------------------ #
    # Signal derivation                                                    #
    # ------------------------------------------------------------------ #

    def _active_ratio(
        self,
        segment: dict[str, Any],
        duration: float,
        state: str | None,
    ) -> float:
        """Fraction of the segment the OS says the user was actually present for.

        The segment's ``state`` decides presence outright; ``idle_time`` only
        discounts a segment already agreed to be active. Deferring to the state
        rather than re-deriving one matters on real data, twice over:

        * Summing idle across every overlapping OS session double-counts
          wall-clock. Some segments overlap a stale 11-hour ``active`` session
          (the artefact migration 0010 was written to repair) *and* the real
          300-second ``idle`` one, and the stale row diluted a genuinely idle
          stretch back to a score of 0.56.
        * ``idle_time`` contradicts its own session constantly — sessions
          labelled idle carry 2, 3 or 10 idle seconds out of several hundred,
          and 18 carry none at all. The label is the reliable half of that pair.

        It also keeps the scorer consistent with the ``state`` column persisted
        beside the score, instead of quietly holding a second opinion.
        """
        if duration <= 0:
            return 0.0
        if state in ("locked", "idle", "gap"):
            return 0.0
        if state != "active":
            # No state recorded: nothing to trust and nothing to discount.
            return 0.5

        session, overlap, span = self._dominant_os_session(segment)
        if session is None or overlap <= 0:
            return 1.0

        idle = self._prorate(getattr(session, "idle_time", 0), overlap, span)

        # The mirror of the idle-session rule above, and for the same reason: when
        # the two halves of a session disagree, the label is the reliable one. 56
        # segments carry an 'active' label while idle_time claims essentially the
        # whole span — among them 12.5 uninterrupted minutes in DB Browser for
        # SQLite, which scored 0.0. Trusting the counter there erases real work.
        if idle >= overlap * self.IDLE_COUNTER_SANITY:
            idle = 0.0

        active_seconds = max(0.0, overlap - min(idle, overlap))
        return max(0.0, min(1.0, active_seconds / duration))

    def _dominant_os_session(self, segment: dict[str, Any]) -> tuple[Any, float, float]:
        """The OS session covering most of the segment — the one that set its state.

        Mirrors ``ActivitySegmentBuilder._determine_state`` so both land on the
        same session, including its first-wins behaviour on a tie.
        """
        best: tuple[Any, float, float] = (None, -1.0, 0.0)
        for session in segment.get("sources", {}).get("os") or []:
            overlap, span = self._session_window(session, segment)
            if overlap > best[1]:
                best = (session, overlap, span)
        return best if best[0] is not None else (None, 0.0, 0.0)

    def _switches_per_min(self, segment: dict[str, Any], duration_min: float) -> float:
        """Rate of attention transitions, preferring the surrounding timeline.

        ``ActivitySegmentBuilder._split_at_boundaries`` cuts a segment at every
        app change and every IDE/browser session edge, so the boundaries *are*
        the switches and counting them inside a segment is close to futile —
        74.5% of scored segments came back with exactly zero, leaving this signal
        pinned at its maximum for 76% of the population and contributing a flat
        bonus instead of a measurement.

        So when a producer supplies ``NEIGHBOURHOOD_KEY`` — the switch rate over
        a window *around* the segment, which both ActivitySegmentBuilder and
        scripts/backfill_focus_scores.py compute — that is used instead. The
        in-segment count below stays as the fallback for callers that score a
        lone segment with no timeline to consult, including most of the tests.
        """
        neighbourhood = segment.get(self.NEIGHBOURHOOD_KEY)
        if isinstance(neighbourhood, (int, float)) and not isinstance(neighbourhood, bool):
            return max(0.0, float(neighbourhood))

        if duration_min <= 0:
            return 0.0
        sources = segment.get("sources", {})

        switches = 0.0
        for ide_session in sources.get("ide") or []:
            overlap, span = self._session_window(ide_session, segment)
            switches += self._prorate(
                getattr(ide_session, "file_switch_count", 0), overlap, span
            )

        # n distinct domains within one segment is n-1 moves between them. The
        # old version counted n, charging a switch to a segment that never left
        # a single site.
        domains = set()
        for browser_session in sources.get("browser") or []:
            if self._session_window(browser_session, segment)[0] <= 0:
                continue
            domain = getattr(browser_session, "domain", None)
            if domain:
                domains.add(domain)
        switches += max(0, len(domains) - 1)

        return switches / duration_min

    def _edits_per_min(self, segment: dict[str, Any], duration_min: float) -> float:
        """Editing rate across IDE sessions overlapping the segment."""
        if duration_min <= 0:
            return 0.0
        edits = 0.0
        for ide_session in segment.get("sources", {}).get("ide") or []:
            overlap, span = self._session_window(ide_session, segment)
            edits += self._prorate(getattr(ide_session, "edit_count", 0), overlap, span)
        return edits / duration_min

    def _edit_bonus(self, components: dict[str, float]) -> float:
        """Bounded reward for dense editing. Zero without IDE data — never a penalty."""
        rate = max(0.0, components.get("edits_per_min", 0.0))
        return self.EDIT_BONUS_MAX * min(rate / self.EDIT_SATURATION, 1.0)

    # ------------------------------------------------------------------ #
    # Session geometry                                                     #
    # ------------------------------------------------------------------ #

    def _session_window(
        self,
        session: Any,
        segment: dict[str, Any],
    ) -> tuple[float, float]:
        """Return ``(overlap_with_segment_sec, session_span_sec)``.

        Both are needed because per-session counters — ``idle_time``,
        ``edit_count``, ``file_switch_count`` — are totals for the whole session
        while a segment is usually a slice of one. Charging a slice the whole
        total is how the old scorer compared a 30-minute session's idle seconds
        against a 2-minute segment's duration.
        """
        start, end = self._session_bounds(session)
        if start is None:
            return 0.0, 0.0
        if end is None:
            # Still open: it covers the rest of the segment by definition.
            end = segment["end_time"]

        span = (end - start).total_seconds()
        overlap = (
            min(end, segment["end_time"]) - max(start, segment["start_time"])
        ).total_seconds()
        return max(0.0, overlap), max(0.0, span)

    def _session_bounds(self, session: Any) -> tuple[Any, Any]:
        """Parsed ``(start, end)`` for a session, memoised on the raw strings.

        ``_session_window`` is reached from four places per segment — presence,
        switching, editing and the concurrency log — so without this the same two
        ISO strings are re-parsed four times over. Roughly 50k redundant parses in
        a full backfill; tidiness rather than a bottleneck.

        Keyed on the timestamp strings rather than the session's identity, so it
        stays a pure-function cache: no dependence on object lifetime, and rows
        sharing a boundary share the entry.
        """
        raw_start = getattr(session, "session_start", None)
        raw_end = getattr(session, "session_end", None)
        key = (raw_start, raw_end)
        cached = self._bounds_cache.get(key)
        if cached is not None:
            return cached

        bounds = (self._parse_or_none(raw_start), self._parse_or_none(raw_end))
        self._bounds_cache[key] = bounds
        return bounds

    @staticmethod
    def _parse_or_none(raw: Any):
        if not raw:
            return None
        try:
            return parse_iso(raw)
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _prorate(total: Any, overlap: float, span: float) -> float:
        """Attribute a whole-session counter to the slice this segment covers."""
        try:
            value = float(total or 0)
        except (TypeError, ValueError):
            return 0.0
        if value <= 0 or span <= 0 or overlap <= 0:
            return 0.0
        return value * min(overlap / span, 1.0)

    def _build_concurrency_log(self, segment: dict[str, Any]) -> dict[str, Any]:
        """Record what else was open during the segment, for later inspection."""
        active_apps: list[dict[str, Any]] = []
        seen_ids: set = set()
        browser_domains: set = set()

        def add_session(session: Any, source_type: str, name: str, extra: dict[str, Any]) -> None:
            session_id = getattr(session, "id", None)
            if session_id is not None and session_id in seen_ids:
                return
            seen_ids.add(session_id)
            overlap, _span = self._session_window(session, segment)
            if overlap <= 0:
                return
            if source_type == "browser":
                domain = getattr(session, "domain", None)
                if domain:
                    browser_domains.add(domain)
            item = {
                "source": source_type,
                "name": name,
                "pid": getattr(session, "process_id", None),
                "overlap_duration_sec": int(overlap),
            }
            item.update(extra)
            active_apps.append(item)

        sources = segment.get("sources", {})
        for os_session in sources.get("os") or []:
            add_session(os_session, "os", getattr(os_session, "app_name", None) or "os", {})
        for ide_session in sources.get("ide") or []:
            name = (
                getattr(ide_session, "ide_name", None)
                or getattr(ide_session, "active_file_name", None)
                or "ide"
            )
            add_session(
                ide_session, "ide", name,
                {"workspace": getattr(ide_session, "workspace_name", None)},
            )
        for browser_session in sources.get("browser") or []:
            add_session(
                browser_session, "browser",
                getattr(browser_session, "browser_name", None) or "browser",
                {
                    "domain": getattr(browser_session, "domain", None),
                    "url": getattr(browser_session, "url", None),
                },
            )

        return {
            "active_applications": active_apps,
            "concurrency_metrics": {
                "max_apps_open": len(active_apps),
                "domain_switches": max(0, len(browser_domains) - 1),
                "source_count": sum(
                    1 for source in ("os", "ide", "browser") if sources.get(source)
                ),
            },
        }
