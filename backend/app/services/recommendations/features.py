"""Feature snapshot construction.

Built once per tick, read by every rule in scope. This is the whole efficiency
argument: the database is touched a fixed number of times regardless of how
many rules run, and a rule costs a dictionary lookup rather than a query.

Two builders. :func:`build_live_context` describes *right now* from the
trailing few hours; :func:`build_daily_context` describes one completed local
day. Both flatten the personal baselines in under ``baseline.*`` keys, so a
rule comparing against a percentile reads it the same way it reads a
measurement.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import joblib

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.recommendations.baselines import (
    BaselineSet,
    DEEP_BLOCK_MIN_SEC,
    DISTRACTION_CATEGORIES,
    SLEEP_GAP_SEC,
    build_blocks,
    build_work_sessions,
    fetch_segments,
)
from app.services.recommendations.effects import post_meeting_focus_effect
from app.repositories.preference_repository import PreferenceRepository
from app.services.recommendations.redaction import (
    TITLE_FEATURES,
    redact_features,
)
from app.services.recommendations.types import FeatureContext

logger = logging.getLogger("smartdesk.recommendations.features")

#: How far back a live tick looks. Long enough to contain the longest run any
#: live rule asks about (LV-17's three-hour no-break check) and nothing more —
#: this is the window the in-memory ring buffer will eventually hold.
LIVE_LOOKBACK_HOURS = 4

#: How far before midnight to reach when locating the current work session's
#: start. Twelve hours covers an evening session that runs past midnight,
#: which is the case that made a same-day lookback wrong.
SESSION_LOOKBACK_HOURS = 12

#: An idle stretch at least this long counts as a break. Below it the user
#: stepped away from the keyboard, not away from the work.
BREAK_MIN_SEC = 300.0

#: Apps that are navigation rather than work. Measured: 48.6 hours in
#: ``explorer`` across the recorded history, which is real friction rather
#: than a rounding error, and it is invisible in a category breakdown because
#: it files as "system".
NAVIGATION_APPS = frozenset({"explorer", "shellhost", "searchapp", "searchhost"})


def _naive_local(value: datetime) -> datetime:
    """Drop the offset from an app-timezone datetime.

    ``activity_segments.start_time_utc`` stores naive local strings despite the
    column name — ``local_date`` on the same row confirms it, and every date
    filter in the app depends on that reading. ``local_now()`` returns an
    aware datetime in the same zone, so stripping the offset lines the two up.
    Comparing them without this raises rather than silently shifting, which is
    the better failure but still a failure.
    """
    return value.replace(tzinfo=None) if value.tzinfo is not None else value


def _domain(detail: str | None) -> str | None:
    if not detail or not detail.lower().startswith(("http://", "https://")):
        return None
    try:
        host = urlparse(detail).netloc.lower()
    except ValueError:
        return None
    return host[4:] if host.startswith("www.") else (host or None)


def _tail(segments: list[dict], as_of: datetime, minutes: float) -> list[dict]:
    """Segments overlapping the trailing ``minutes`` before ``as_of``."""
    cutoff = as_of - timedelta(minutes=minutes)
    return [s for s in segments if s["end"] > cutoff]


def _overlap_sec(segment: dict, start: datetime, end: datetime) -> float:
    return max(
        0.0,
        (min(segment["end"], end) - max(segment["start"], start)).total_seconds(),
    )


def _trailing_run(segments: list[dict], as_of: datetime, predicate) -> float:
    """Length in minutes of the run ending at ``as_of`` where ``predicate`` holds.

    Walks backwards from the most recent segment and stops at the first one
    that fails, so it measures the *current* stretch rather than the longest
    one anywhere in the lookback.
    """
    if not segments:
        return 0.0
    total = 0.0
    previous_start: datetime | None = None
    for segment in reversed(segments):
        if not predicate(segment):
            break
        # A wall-clock hole means the run already ended; the segments before it
        # belong to an earlier stretch.
        if previous_start is not None and (previous_start - segment["end"]).total_seconds() > 120:
            break
        total += segment["duration"]
        previous_start = segment["start"]
    return total / 60.0


def _switch_rate(segments: list[dict], minutes: float) -> float:
    """App changes per minute across a set of segments.

    Counts transitions where ``app_name`` actually changed. The segment
    splitter also cuts at IDE/browser session edges and at its 900 s cap, and
    those boundaries mean no attention moved — the same correction
    ``FocusScorer.neighbourhood_switch_rates`` makes.
    """
    if minutes <= 0 or len(segments) < 2:
        return 0.0
    changes = sum(
        1 for a, b in zip(segments, segments[1:]) if a["app"] != b["app"]
    )
    return changes / minutes


def _ide_activity(db: Session, user_id: str, start: datetime, end: datetime) -> dict:
    """Edit counts and foreground time from the IDE extension.

    Absent when the extension is not reporting, which is a real and frequent
    state — HY-01 exists precisely to notice it — so every key here is
    optional and the rules requiring them are gated out rather than defaulting
    to zero and reading as "no edits".
    """
    rows = db.execute(
        text("""
            SELECT session_start, session_end, duration_sec, edit_count,
                   is_foreground, workspace_name
            FROM ide_sessions
            WHERE user_id = :user_id
              AND session_start >= :start
              AND session_start < :end
        """),
        {
            "user_id": user_id,
            "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ).mappings().all()

    if not rows:
        return {}

    edits = sum(int(r["edit_count"] or 0) for r in rows)
    foreground_sec = sum(
        float(r["duration_sec"] or 0) for r in rows if r["is_foreground"]
    )
    span_min = max(1.0, (end - start).total_seconds() / 60.0)
    return {
        "ide_edits": float(edits),
        "ide_foreground_min": foreground_sec / 60.0,
        "ide_edits_per_min": edits / span_min,
        "ide_workspace": next(
            (r["workspace_name"] for r in reversed(rows) if r["workspace_name"]), None
        ),
    }


def _calendar_context(db: Session, user_id: str, as_of: datetime) -> dict:
    """Minutes to the next event, and whether one is running now."""
    rows = db.execute(
        text("""
            SELECT title, start_time, end_time
            FROM calendar_events
            WHERE user_id = :user_id
              AND status != 'cancelled'
              AND end_time >= :from_time
            ORDER BY start_time
            LIMIT 20
        """),
        {"user_id": user_id, "from_time": (as_of - timedelta(hours=2)).isoformat()},
    ).mappings().all()

    out: dict = {}
    for row in rows:
        try:
            start = datetime.fromisoformat(row["start_time"])
            end = datetime.fromisoformat(row["end_time"])
        except (TypeError, ValueError):
            continue
        if start.tzinfo is not None:
            start = start.replace(tzinfo=None)
            end = end.replace(tzinfo=None)
        if start <= as_of < end:
            out["in_meeting"] = 1.0
            out["meeting_title"] = row["title"] or "your meeting"
            out["meeting_ends_in_min"] = (end - as_of).total_seconds() / 60.0
            break
        if start > as_of:
            out["minutes_to_next_meeting"] = (start - as_of).total_seconds() / 60.0
            out["next_meeting_title"] = row["title"] or "your next meeting"
            break
    return out


# ---------------------------------------------------------------------- #
# Live                                                                     #
# ---------------------------------------------------------------------- #

def build_live_context(
    db: Session,
    user_id: str,
    as_of: datetime,
    baselines: BaselineSet,
) -> FeatureContext:
    """Snapshot describing the present moment."""
    as_of = _naive_local(as_of)
    day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    lookback_start = as_of - timedelta(hours=LIVE_LOOKBACK_HOURS)

    # One fetch, three views. The widest thing any live feature needs is the
    # start of the current work session, which for an evening-into-morning
    # stretch began before midnight -- so the span reaches back past the day
    # boundary and `recent` and `today` are sliced out of it in Python. Two
    # separate queries here previously read overlapping ranges and still could
    # not see far enough back to find a session start.
    span_start = min(lookback_start, day_start - timedelta(hours=SESSION_LOOKBACK_HOURS))
    span = fetch_segments(db, user_id, span_start, as_of + timedelta(minutes=1))
    recent = [s for s in span if s["end"] > lookback_start]
    today = [s for s in span if s["start"] >= day_start]

    data: dict = {
        "now_hour": float(as_of.hour),
        "weekday": float(as_of.weekday()),
        "minutes_into_day": float(as_of.hour * 60 + as_of.minute),
    }

    if recent:
        latest = recent[-1]
        # Only describe a "current" activity if the newest segment is actually
        # recent. Opening the app after an hour away must not report whatever
        # was in the foreground when the machine was last used.
        staleness_min = (as_of - latest["end"]).total_seconds() / 60.0
        data["data_staleness_min"] = staleness_min
        if staleness_min <= 10:
            data["current_app"] = latest["app"]
            data["current_title"] = latest["title"]
            data["current_detail"] = latest["detail"]
            data["current_category"] = latest["category"]
            data["current_state"] = latest["state"]

        data["active_run_min"] = _trailing_run(
            recent, as_of, lambda s: s["state"] == "active"
        )
        data["entertainment_run_min"] = _trailing_run(
            recent, as_of,
            lambda s: s["state"] == "active" and s["category"] in DISTRACTION_CATEGORIES,
        )
        data["navigation_run_min"] = _trailing_run(
            recent, as_of,
            lambda s: (s["app"] or "").lower() in NAVIGATION_APPS,
        )

        last_15 = _tail(recent, as_of, 15)
        data["switch_rate_15m"] = _switch_rate(last_15, 15.0)
        last_10 = _tail(recent, as_of, 10)
        data["category_switches_10m"] = float(sum(
            1 for a, b in zip(last_10, last_10[1:]) if a["category"] != b["category"]
        ))
        data["unique_domains_10m"] = float(len({
            d for d in (_domain(s["detail"]) for s in last_10) if d
        }))

        last_30 = _tail(recent, as_of, 30)
        focus_weight = sum(s["duration"] for s in last_30 if s["focus"] is not None)
        if focus_weight > 0:
            data["recent_focus"] = sum(
                (s["focus"] or 0) * s["duration"] for s in last_30
                if s["focus"] is not None
            ) / focus_weight

        window_30 = as_of - timedelta(minutes=30)
        data["navigation_min_30m"] = sum(
            _overlap_sec(s, window_30, as_of) for s in recent
            if (s["app"] or "").lower() in NAVIGATION_APPS
        ) / 60.0

        # Time since the last real break, and the gap we just came back from.
        last_break_end: datetime | None = None
        for segment in reversed(recent):
            if segment["state"] in ("idle", "locked") and segment["duration"] >= BREAK_MIN_SEC:
                last_break_end = segment["end"]
                data["last_break_min"] = segment["duration"] / 60.0
                break
        if last_break_end is not None:
            data["minutes_since_break"] = (as_of - last_break_end).total_seconds() / 60.0
            if (as_of - last_break_end).total_seconds() <= 300:
                data["just_returned"] = 1.0
        elif recent:
            data["minutes_since_break"] = (
                as_of - recent[0]["start"]
            ).total_seconds() / 60.0

        # The work context to offer back after an interruption.
        for segment in reversed(recent):
            if segment["category"] == "work" and segment["state"] == "active":
                data["last_work_app"] = segment["app"]
                data["last_work_title"] = segment["title"] or segment["app"]
                data["last_work_detail"] = segment["detail"]
                break

        # Repeated re-entry into the same context — an unfinished task being
        # picked up and dropped rather than a single sustained stretch.
        visits: dict[tuple, int] = {}
        for segment in recent:
            if segment["state"] != "active" or not segment["title"]:
                continue
            key = (segment["app"], segment["title"][:60])
            visits[key] = visits.get(key, 0) + 1
        if visits:
            (top_app, top_title), count = max(visits.items(), key=lambda kv: kv[1])
            data["repeat_context_count"] = float(count)
            data["repeat_context_title"] = top_title
            data["repeat_context_app"] = top_app

    if today:
        active_today = [s for s in today if s["state"] == "active"]
        data["today_active_min"] = sum(s["duration"] for s in active_today) / 60.0
        if active_today:
            first = active_today[0]
            data["day_first_category"] = first["category"]
            data["day_start_hour"] = first["start"].hour + first["start"].minute / 60.0
        # "Now" on the same continuous scale the stop_hour baseline uses, so a
        # 01:00 that continues last night's session reads as 25.0 and compares
        # against a p90 of 32.7 correctly. Comparing a raw 0-23 clock against
        # that scale is how LV-15 would silently stop firing after midnight.
        sessions = build_work_sessions(span)
        if sessions:
            current = sessions[-1]
            if (as_of - current.end).total_seconds() < SLEEP_GAP_SEC:
                days_over = (as_of.date() - current.start.date()).days
                data["session_hour_now"] = (
                    as_of.hour + as_of.minute / 60.0 + 24.0 * days_over
                )
                data["session_run_min"] = (
                    as_of - current.start
                ).total_seconds() / 60.0

        hour_start = as_of.replace(minute=0, second=0, microsecond=0)
        data["social_min_this_hour"] = sum(
            _overlap_sec(s, hour_start, as_of) for s in today
            if s["category"] in DISTRACTION_CATEGORIES
        ) / 60.0

    data.update(_ide_activity(db, user_id, as_of - timedelta(minutes=20), as_of))
    data.update(_calendar_context(db, user_id, as_of))

    # Baselines, flattened. Absent metrics stay absent so the gate can see it.
    data.update(baselines.flatten())
    peaks = baselines.peak_hours()
    if peaks:
        data["peak_hours"] = peaks
        data["peak_hour_top"] = float(peaks[0])
        next_peak = min(
            ((h - as_of.hour) % 24 for h in peaks),
            default=None,
        )
        if next_peak is not None:
            data["hours_to_peak"] = float(next_peak)
    troughs = baselines.trough_hours()
    if troughs:
        data["trough_hours"] = troughs
    if as_of.hour in baselines.hour_focus:
        data["hour_focus_now"] = baselines.hour_focus[as_of.hour]

    # Titles are free text written by software the user does not control, and
    # they reach card copy and exported reports. Scrubbed here, at the one
    # boundary every context passes through, rather than at each render site.
    redact_features(data, TITLE_FEATURES)
    data["pref.sensitivity"] = PreferenceRepository(db).sensitivity(user_id)
    return FeatureContext(
        data,
        as_of=as_of,
        user_id=user_id,
        days_of_history=baselines.days_of_history,
    )


# ---------------------------------------------------------------------- #
# Daily                                                                    #
# ---------------------------------------------------------------------- #

#: Foreground app names that mean "an IDE was open". HY-01 compares this
#: against the IDE extension's own rows: the OS collector always sees the
#: editor window, so the two disagreeing is exactly the signal that the
#: extension has stopped reporting.
IDE_APPS = frozenset({"code", "antigravity ide", "cursor", "windsurf", "devenv"})

#: Hours a meeting can reasonably be scheduled into. PL-02 picks the
#: weakest hour *inside* this band rather than the weakest hour overall.
MEETING_BAND = (8, 18)

#: Browser process names, for the HY-02 cross-check between what the OS
#: collector saw in the foreground and what the browser extension reported.
BROWSER_APPS = frozenset({
    "comet", "chrome", "msedge", "firefox", "brave", "opera", "vivaldi",
    "safari", "arc", "zen", "chromium",
})


def _hygiene_features(db: Session, user_id: str, day_start: datetime, segments: list[dict]) -> dict:
    """Signals about the collection pipeline itself, not about the user."""
    data: dict = {}
    day_end = day_start + timedelta(days=1)

    ide_app_sec = sum(
        s["duration"] for s in segments
        if (s["app"] or "").lower() in IDE_APPS and s["state"] == "active"
    )
    data["ide_app_min_today"] = ide_app_sec / 60.0
    data["ide_sessions_today"] = float(db.execute(
        text("""
            SELECT COUNT(*) FROM ide_sessions
            WHERE user_id = :user_id AND session_start >= :start AND session_start < :end
        """),
        {
            "user_id": user_id,
            "start": day_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": day_end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ).scalar() or 0)

    last_sync = db.execute(
        text("SELECT MAX(last_synced_at) FROM calendar_events WHERE user_id = :u"),
        {"u": user_id},
    ).scalar()
    if last_sync:
        try:
            synced = datetime.fromisoformat(str(last_sync))
            if synced.tzinfo is not None:
                synced = synced.replace(tzinfo=None)
            data["calendar_age_hours"] = max(
                0.0, (day_end - synced).total_seconds() / 3600.0
            )
        except (TypeError, ValueError):
            pass

    last_run = db.execute(
        text("SELECT MAX(run_date) FROM activity_window_patterns")
    ).scalar()
    if last_run:
        try:
            ran = datetime.fromisoformat(f"{last_run}T00:00:00")
            data["pattern_age_hours"] = max(
                0.0, (day_end - ran).total_seconds() / 3600.0
            )
        except (TypeError, ValueError):
            pass

    newest_segment = db.execute(
        text("SELECT MAX(start_time_utc) FROM activity_segments WHERE user_id = :u"),
        {"u": user_id},
    ).scalar()
    newest_window = db.execute(
        text("SELECT MAX(window_end) FROM activity_window_10m")
    ).scalar()
    if newest_segment and newest_window:
        try:
            lag = (
                datetime.fromisoformat(str(newest_segment))
                - datetime.fromisoformat(str(newest_window))
            ).total_seconds() / 60.0
            data["window_lag_min"] = max(0.0, lag)
        except (TypeError, ValueError):
            pass

    browser_app_sec = sum(
        s["duration"] for s in segments
        if (s["app"] or "").lower() in BROWSER_APPS and s["state"] == "active"
    )
    data["browser_app_min_today"] = browser_app_sec / 60.0
    data["browser_sessions_today"] = float(db.execute(
        text("""
            SELECT COUNT(*) FROM browser_sessions
            WHERE user_id = :user_id AND session_start >= :start AND session_start < :end
        """),
        {
            "user_id": user_id,
            "start": day_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end": day_end.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    ).scalar() or 0)

    # HY-08 — rows that cannot be true. A future-dated segment or a negative
    # duration poisons every percentile silently, so it is worth one COUNT.
    data["impossible_segments"] = float(db.execute(
        text("""
            SELECT COUNT(*) FROM activity_segments
            WHERE user_id = :u
              AND (duration_sec < 0 OR end_time_utc < start_time_utc
                   OR start_time_utc > :future)
        """),
        {"u": user_id, "future": (day_end + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")},
    ).scalar() or 0)

    return data


#: Cached ``(mtime, fields)`` from the categoriser artefact. The model is frozen
#: once trained — the file's own module says so — yet the two scalars HY-09
#: needs were being unpickled off disk on every daily context build, which is
#: also every daily report request. Keyed on mtime so a retrain is picked up.
_MODEL_META: tuple[float, dict] | None = None


def _model_meta(path: Path) -> dict:
    """The categoriser's self-reported quality, read at most once per retrain."""
    global _MODEL_META
    mtime = path.stat().st_mtime
    if _MODEL_META is not None and _MODEL_META[0] == mtime:
        return _MODEL_META[1]

    payload = joblib.load(path)
    fields: dict = {"model_basis": str(payload.get("holdout_basis") or "unknown")}
    accuracy = payload.get("holdout_accuracy")
    if accuracy is not None:
        fields["model_holdout"] = float(accuracy)

    _MODEL_META = (mtime, fields)
    return fields


def _model_health(db: Session) -> dict:
    """How stale the categoriser is against the labels it has not seen.

    Drift here is not a slow decay in the coefficients — the model is frozen
    once trained. It is that corrections keep arriving and the model keeps not
    learning from them, so its holdout figure describes a model that no longer
    matches the labelled data. Counting unused labels measures exactly that,
    and needs no second copy of the training history.
    """
    data: dict = {}
    try:
        from app.core.config import settings as app_settings

        path = Path(app_settings.MODEL_STORE_DIR) / "categorizer.joblib"
        if not path.exists():
            data["model_missing"] = 1.0
            return data

        # The label count below is deliberately *not* cached: corrections arrive
        # continuously, and that number moving is the whole signal HY-09 reads.
        data.update(_model_meta(path))
    except Exception:
        logger.debug("Could not read the categoriser model for HY-09")
        return data

    unused = db.execute(
        text("""
            SELECT COUNT(*) FROM activity_segment_labels
            WHERE used_in_training = 0
        """)
    ).scalar()
    data["labels_unused"] = float(unused or 0)
    return data


def build_daily_context(
    db: Session,
    user_id: str,
    day: datetime,
    baselines: BaselineSet,
) -> FeatureContext:
    """Snapshot describing one completed local day."""
    day_start = _naive_local(day).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    segments = fetch_segments(db, user_id, day_start, day_end)

    data: dict = {
        "local_date": day_start.strftime("%Y-%m-%d"),
        "weekday": float(day_start.weekday()),
    }
    data.update(_hygiene_features(db, user_id, day_start, segments))

    peaks = baselines.peak_hours()
    if peaks:
        data["peak_hour_top"] = float(peaks[0])
    # Restricted to hours a meeting could plausibly be held in; see
    # BaselineSet.trough_hours_within for why the raw statistical trough
    # is not usable for this one.
    troughs = baselines.trough_hours_within(MEETING_BAND[0], MEETING_BAND[1])
    if troughs:
        data["trough_hour_top"] = float(troughs[0])

    active = [s for s in segments if s["state"] == "active"]
    if not active:
        data.update(baselines.flatten())
        redact_features(data, TITLE_FEATURES)
        data["pref.sensitivity"] = PreferenceRepository(db).sensitivity(user_id)
        return FeatureContext(
            data, as_of=day_start, user_id=user_id,
            days_of_history=baselines.days_of_history,
        )

    active_sec = sum(s["duration"] for s in active)
    idle_sec = sum(s["duration"] for s in segments if s["state"] == "idle")

    data["active_min"] = active_sec / 60.0
    data["idle_min"] = idle_sec / 60.0
    data["segment_count"] = float(len(active))
    data["frag_index"] = len(active) / max(active_sec / 3600.0, 1e-6)
    if active_sec + idle_sec > 0:
        data["idle_share"] = idle_sec / (active_sec + idle_sec)

    distraction_sec = sum(
        s["duration"] for s in active if s["category"] in DISTRACTION_CATEGORIES
    )
    data["distraction_share"] = distraction_sec / active_sec
    data["distraction_min"] = distraction_sec / 60.0

    # Only a day that actually began — one whose first activity follows a
    # sleep-sized break — has a start hour worth comparing. A calendar day that
    # simply continues the previous night's session does not, and reporting
    # 00:0x for it is what broke the start-hour baseline. See SLEEP_GAP_SEC.
    previous_end = db.execute(
        text("""
            SELECT MAX(end_time_utc) FROM activity_segments
            WHERE user_id = :u AND state = 'active' AND end_time_utc <= :start
        """),
        {"u": user_id, "start": day_start.strftime("%Y-%m-%d %H:%M:%S")},
    ).scalar()
    started_fresh = True
    if previous_end:
        try:
            gap = (active[0]["start"] - datetime.fromisoformat(str(previous_end))).total_seconds()
            started_fresh = gap >= SLEEP_GAP_SEC
        except (TypeError, ValueError):
            pass
    if started_fresh:
        data["day_start_hour"] = active[0]["start"].hour + active[0]["start"].minute / 60.0
    # The stop time of the last work session that *began* on this day, on the
    # continuous scale. Using the calendar day's last segment instead reported
    # 23:59 for every session that ran past midnight.
    day_sessions = [
        session for session in build_work_sessions(segments)
        if session.start.date() == day_start.date()
    ]
    if day_sessions:
        data["day_stop_hour"] = day_sessions[-1].stop_hour

    # Blocks and deep work.
    blocks = build_blocks(segments)
    focus_bar = baselines.global_stats.get("focus")
    deep_bar = focus_bar.p75 if focus_bar and focus_bar.usable else 0.5
    deep_blocks = [
        b for b in blocks if b.seconds >= DEEP_BLOCK_MIN_SEC and b.focus >= deep_bar
    ]
    data["deep_work_min"] = sum(b.seconds for b in deep_blocks) / 60.0
    data["deep_block_count"] = float(len(deep_blocks))
    if blocks:
        longest = max(blocks, key=lambda b: b.seconds)
        data["longest_block_min"] = longest.seconds / 60.0
        data["longest_block_start"] = longest.start.strftime("%H:%M")

    # Switching.
    data["switch_total"] = float(sum(
        1 for a, b in zip(active, active[1:]) if a["app"] != b["app"]
    ))

    # Category mix, and how far it sits from the personal norm.
    mix: dict[str, float] = {}
    for segment in active:
        key = segment["category"] or "uncategorised"
        mix[key] = mix.get(key, 0.0) + segment["duration"]
    data["category_mix"] = {k: v / active_sec for k, v in mix.items()}
    top_category, top_seconds = max(mix.items(), key=lambda kv: kv[1])
    data["top_category"] = top_category
    data["top_category_min"] = top_seconds / 60.0
    data["top_category_share"] = top_seconds / active_sec
    data["uncategorised_share"] = mix.get("uncategorised", 0.0) / active_sec

    # Hour-by-hour focus for this day, and the best and worst of them.
    hours: dict[int, tuple[float, float]] = {}
    for segment in active:
        if segment["focus"] is None:
            continue
        hour = segment["start"].hour
        weighted, duration = hours.get(hour, (0.0, 0.0))
        hours[hour] = (
            weighted + segment["focus"] * segment["duration"],
            duration + segment["duration"],
        )
    # A twenty-minute floor: an hour holding one two-minute glance is not the
    # day's best hour, however well that glance happened to score.
    scored = {
        hour: weighted / duration
        for hour, (weighted, duration) in hours.items()
        if duration >= 1200
    }
    if scored:
        best = max(scored.items(), key=lambda kv: kv[1])
        worst = min(scored.items(), key=lambda kv: kv[1])
        data["best_hour"] = float(best[0])
        data["best_hour_focus"] = best[1]
        data["worst_hour"] = float(worst[0])
        data["worst_hour_focus"] = worst[1]
        data["scored_hour_count"] = float(len(scored))

    focus_weight = sum(s["duration"] for s in active if s["focus"] is not None)
    if focus_weight > 0:
        data["day_focus"] = sum(
            (s["focus"] or 0) * s["duration"] for s in active if s["focus"] is not None
        ) / focus_weight

    # Anomalous windows, straight from the clustering already stored nightly.
    anomalies = db.execute(
        text("""
            SELECT window_start, anomaly_score, avg_focus_score
            FROM activity_window_patterns
            WHERE scope = 'day' AND substr(window_start, 1, 10) = :date
            ORDER BY anomaly_score ASC
            LIMIT 5
        """),
        {"date": data["local_date"]},
    ).mappings().all()
    negative = [a for a in anomalies if (a["anomaly_score"] or 0) < 0]
    if negative:
        data["anomaly_count"] = float(len(negative))
        data["anomaly_worst_at"] = str(negative[0]["window_start"])[11:16]

    # DY-11 — how far today's category mix sits from the personal norm, as an
    # L1 distance over shares. Bounded in [0, 2], where 0 is an identical mix.
    if baselines.category_mix:
        keys = set(data["category_mix"]) | set(baselines.category_mix)
        data["mix_distance"] = sum(
            abs(data["category_mix"].get(k, 0.0) - baselines.category_mix.get(k, 0.0))
            for k in keys
        )
        drift = {
            k: data["category_mix"].get(k, 0.0) - baselines.category_mix.get(k, 0.0)
            for k in keys
        }
        gained = max(drift.items(), key=lambda kv: kv[1])
        lost = min(drift.items(), key=lambda kv: kv[1])
        data["mix_up"], data["mix_up_delta"] = gained
        data["mix_down"], data["mix_down_delta"] = lost

    # DY-10 — the matched post-meeting comparison. Returns None far more often
    # than not; that is the evidence floor doing its job, not a failure.
    effect = post_meeting_focus_effect(
        db, user_id, day_start - timedelta(days=30), day_start + timedelta(days=1)
    )
    if effect is not None:
        data["post_meeting_focus"] = effect.treated_median
        data["control_focus"] = effect.control_median
        data["post_meeting_relative"] = effect.relative
        data["post_meeting_n"] = float(min(effect.n_treated, effect.n_control))
        data["post_meeting_p"] = effect.pair_p
        data["post_meeting_pairs"] = float(effect.n_pairs)

    # PL-08 — the app pair you bounce between most. Counted as an unordered
    # pair, because A->B and B->A are the same habit seen from two sides.
    transitions: dict[tuple[str, str], int] = {}
    for earlier, later in zip(active, active[1:]):
        a, b = earlier["app"], later["app"]
        if not a or not b or a == b:
            continue
        key = (a, b) if a < b else (b, a)
        transitions[key] = transitions.get(key, 0) + 1
    if transitions:
        (pair_a, pair_b), count = max(transitions.items(), key=lambda kv: kv[1])
        data["switch_pair_a"] = pair_a
        data["switch_pair_b"] = pair_b
        data["switch_pair_count"] = float(count)

    # PL-03 — meetings already booked inside the hours you score highest in.
    peaks = baselines.peak_hours()
    if peaks:
        upcoming = db.execute(
            text("""
                SELECT title, start_time
                FROM calendar_events
                WHERE user_id = :user_id AND status != 'cancelled'
                  AND start_time >= :start AND start_time < :end
                ORDER BY start_time
            """),
            {
                "user_id": user_id,
                "start": day_start.isoformat(),
                "end": (day_start + timedelta(days=7)).isoformat(),
            },
        ).mappings().all()
        clashes = []
        for row in upcoming:
            try:
                when = datetime.fromisoformat(str(row["start_time"]))
            except (TypeError, ValueError):
                continue
            if when.hour in peaks:
                clashes.append((row["title"] or "an event", when))
        if clashes:
            data["peak_clash_count"] = float(len(clashes))
            data["peak_clash_title"] = clashes[0][0]
            data["peak_clash_hour"] = float(clashes[0][1].hour)

    # PL-07 — learning share against the personal norm.
    learn_share = (data["category_mix"] or {}).get("learn", 0.0)
    data["learn_share"] = learn_share
    if baselines.category_mix:
        data["learn_share_usual"] = baselines.category_mix.get("learn", 0.0)

    # HY-09 — whether the categoriser has fallen behind its own labels.
    data.update(_model_health(db))

    # HY-06 — how much of the day the classifier was unsure about.
    scored = [s for s in active if s["confidence"] is not None]
    if scored:
        low = sum(s["duration"] for s in scored if (s["confidence"] or 0) < 0.5)
        data["low_confidence_share"] = low / active_sec

    data.update(baselines.flatten())
    redact_features(data, TITLE_FEATURES)
    data["pref.sensitivity"] = PreferenceRepository(db).sensitivity(user_id)
    return FeatureContext(
        data,
        as_of=day_start,
        user_id=user_id,
        days_of_history=baselines.days_of_history,
    )
