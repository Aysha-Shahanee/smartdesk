"""Activity segment builder service.

Implements the core logic for building canonical activity segments from
raw OS, IDE, and browser session data according to the corrected design.
"""

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session as DbSession

from app.core.database import SessionLocal
from app.core.time import local_now_iso, local_now
from app.core.time import parse_iso
from app.core.time import to_local_iso
from app.models.db import ActivitySegmentLabelRecord
from app.models.db import ActivitySegmentRecord
from app.models.db import BrowserSessionRecord
from app.models.db import IDESessionRecord
from app.models.db import OSSessionRecord
from app.repositories.activity_segment_repository import ActivitySegmentRepository
from app.repositories.browser_session_repository import BrowserSessionRepository
from app.repositories.ide_session_repository import IDESessionRepository
from app.repositories.os_session_repository import OSSessionRepository
from app.services.categorizer import Categorizer
from app.services.focus_scorer import NEIGHBOURHOOD_WINDOW_SEC
from app.services.focus_scorer import FocusScorer
from app.services.focus_scorer import neighbourhood_switch_rates
from app.services.embedder import embedder

logger = logging.getLogger(__name__)

# How often the background thread wakes up to build segments.
BUILD_INTERVAL_SEC: int = 300  # 5 minutes

# How long to wait for delayed events before processing.
EVENT_ARRIVAL_DELAY_SECONDS: int = 30

# Most wall-clock time one tick will process. A tick used to cover exactly
# BUILD_INTERVAL_SEC ending at now, so anything the builder was not awake for —
# a restart, a suspend, a slow tick — was never processed and never revisited.
# The watermark makes ticks resume from where the last one stopped instead, and
# this bounds how much a single catch-up tick may chew through.
MAX_CATCHUP_SPAN_SEC: int = 6 * 3600

# Segments are cut at this length so one long focus block becomes a run of
# bounded rows rather than a single unwieldy one.
MAX_SEGMENT_SEC: int = 900

# Shortest segment worth scoring. Below this the per-minute rates the focus
# scorer derives are dominated by rounding, so no score is written at all —
# better an honest NULL than a confident number built from three seconds.
MIN_SCORABLE_SEC: int = 5

# Whether to synthesise "gap" rows over stretches no OS session covers.
#
# Off: activity_segments must never claim more wall-clock than os_sessions, the
# table it derives from. With gap-filling on, every window got a row and the
# timeline read a continuous 24 h/day — 108.3 h of synthetic gap against 81.8 h
# of real OS coverage for 2026-07-21..28. That reproduced the look of the very
# artefact this work removed, and asserted "no data" over stretches where
# browser_sessions held 52 h of records.
#
# With it off, absence of a row means no data. Idle time is still represented:
# it comes through as state='idle' from the OS session itself, not as a synthetic
# row. See _determine_state.
EMIT_GAP_SEGMENTS: bool = False


class ActivitySegmentBuilder:
    """Builds canonical activity segments from raw session data.

    Usage::

        builder = ActivitySegmentBuilder()
        builder.start()   # call once at application startup

    The builder stops automatically when the process exits because the timer
    thread is a daemon thread.
    """

    def __init__(
        self,
        user_id: str = "local_user",
        device_id: str = "",
    ) -> None:
        """Initialize the activity segment builder.

        Args:
            user_id: User identifier to process segments for
            device_id: Device identifier to process segments for (empty for current device)
        """
        self._user_id = user_id
        # Handle empty device_id by getting the actual hostname
        if not device_id:
            import socket
            self._device_id = socket.gethostname().lower()
        else:
            self._device_id = device_id
        self._timer: threading.Timer | None = None
        self._running = False
        self._interval_seconds = BUILD_INTERVAL_SEC
        self.logger = logging.getLogger(__name__)

    def start(
        self,
        user_id: str | None = None,
        device_id: str | None = None,
        interval_seconds: int | None = None,
    ) -> None:
        """Start the recurring background timer.

        Every argument defaults to whatever ``__init__`` was given, so calling
        ``start()`` bare keeps the identity the builder was constructed with.
        A second definition of this method used to shadow this one with defaults
        of ``user_id="local_user", device_id=""``, which meant the bare call in
        main.py silently discarded ``settings.DEFAULT_USER_ID`` and
        ``settings.DEVICE_ID`` and processed whatever those literals named.

        Args:
            user_id: Override the user to process segments for
            device_id: Override the device (empty or None keeps the current one)
            interval_seconds: Override how often the builder runs
        """
        if self._running:
            self.logger.warning("ActivitySegmentBuilder already running — ignoring start().")
            return

        if user_id:
            self._user_id = user_id
        if device_id:
            self._device_id = device_id
        if interval_seconds:
            self._interval_seconds = interval_seconds

        self._running = True
        self.logger.info(
            "ActivitySegmentBuilder started (interval=%ds, user=%s, device=%s).",
            self._interval_seconds, self._user_id, self._device_id,
        )
        self._schedule()

    def stop(self) -> None:
        """Cancel the next scheduled run (best-effort, does not interrupt a running cycle)."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.logger.info("ActivitySegmentBuilder stopped.")

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _schedule(self) -> None:
        if not self._running:
            return
        self._timer = threading.Timer(self._interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-activity-segment-builder"
        self._timer.start()

    def _tick(self) -> None:
        """One cycle: build segments for recent time window, then reschedule."""
        try:
            self._build_recent_segments()
        except Exception:
            self.logger.exception("ActivitySegmentBuilder encountered an error during tick.")
        finally:
            self._schedule()

    def _resolve_watermark(self, db: DbSession, now: datetime) -> datetime:
        """Where the next build window should start.

        The furthest point already covered by a segment, falling back to one
        interval ago on a cold start. Without this the builder processed only
        ``[now - 5 min, now]`` every tick and never revisited a window it missed,
        so any gap in its own uptime became a permanent hole in the timeline.
        """
        latest = (
            db.query(ActivitySegmentRecord.end_time_utc)
            .filter(ActivitySegmentRecord.user_id == self._user_id)
            .order_by(ActivitySegmentRecord.end_time_utc.desc())
            .limit(1)
            .scalar()
        )
        if latest is None:
            return now - timedelta(seconds=self._interval_seconds)
        if isinstance(latest, str):
            latest = parse_iso(latest)
        latest = latest if latest.tzinfo else latest.replace(tzinfo=now.tzinfo)
        # Never chew through more than one catch-up span in a single tick.
        return max(latest, now - timedelta(seconds=MAX_CATCHUP_SPAN_SEC))

    def _build_recent_segments(self) -> None:
        """Build activity segments from the watermark up to now."""
        db: DbSession = SessionLocal()
        try:
            end_time = local_now()
            start_time = self._resolve_watermark(db, end_time)

            # The arrival delay is applied once, inside
            # _build_segments_for_timerange. Subtracting it here as well took it
            # off twice; that went unnoticed while the inverted ternary in
            # _calculate_safe_processing_end was discarding the result anyway.
            safe_end_time = end_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)
            if start_time >= safe_end_time:
                # Normal when a tick fires with nothing new to cover.
                self.logger.debug(
                    f"Nothing to build: watermark {start_time.isoformat()} "
                    f">= safe end {safe_end_time.isoformat()}"
                )
                return

            # Initialize repositories with current database session
            os_repo = OSSessionRepository()
            ide_repo = IDESessionRepository()
            browser_repo = BrowserSessionRepository()
            segment_repo = ActivitySegmentRepository()

            # Build segments for the time range
            segments = self._build_segments_for_timerange(
                db=db,
                user_id=self._user_id,
                device_id=self._device_id,
                start_time_iso=start_time.isoformat(),
                end_time_iso=end_time.isoformat(),
                os_repo=os_repo,
                ide_repo=ide_repo,
                browser_repo=browser_repo,
                segment_repo=segment_repo,
            )

            if segments:
                self.logger.info(
                    f"Built {len(segments)} activity segments for user {self._user_id} "
                    f"on device {self._device_id or 'default'}"
                )
            else:
                self.logger.debug(
                    f"No activity segments built for user {self._user_id} "
                    f"on device {self._device_id or 'default'}"
                )

        except Exception:
            self.logger.exception("ActivitySegmentBuilder failed to build segments")
        finally:
            db.close()

    def backfill(
        self,
        from_iso: str,
        to_iso: str,
        chunk_sec: int = 3600,
        purge: bool = True,
    ) -> dict:
        """Rebuild segments across an explicit range, in chunks.

        The only way to reprocess history. ``run_once()`` cannot do it — it
        recomputes ``now - interval`` like a normal tick, so a window the
        builder was never awake for stayed empty forever.

        Old segments in the range are deleted before rebuilding. ``_upsert_segments``
        matches on an exact ``(start_time_utc, end_time_utc)`` pair, and rebuilt
        boundaries move once clipping and length-splitting apply — so without a
        purge the old rows would survive alongside the new ones and the range
        would be double-counted.

        Deleting them would strand ``activity_segment_labels``, whose ``segment_id``
        points at rows about to disappear and whose IDs are random UUIDs rather
        than derived from content. Labels are therefore anchored to a timestamp
        first and re-pointed at whichever rebuilt segment covers it.

        Args:
            from_iso: Range start (ISO 8601)
            to_iso: Range end (ISO 8601)
            chunk_sec: Wall-clock seconds per chunk; each is its own transaction
            purge: Delete existing segments in range before rebuilding

        Returns:
            Summary dict with the range covered, chunks, segments and labels.
        """
        start = parse_iso(from_iso)
        end = parse_iso(to_iso)
        if start >= end:
            raise ValueError(f"backfill range is empty: {from_iso} -> {to_iso}")

        anchors = self._snapshot_label_anchors(start, end) if purge else []

        os_repo = OSSessionRepository()
        ide_repo = IDESessionRepository()
        browser_repo = BrowserSessionRepository()
        segment_repo = ActivitySegmentRepository()

        chunks = 0
        built = 0
        purged = 0
        failed = 0
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(seconds=chunk_sec), end)
            db: DbSession = SessionLocal()
            try:
                if purge:
                    purged += (
                        db.query(ActivitySegmentRecord)
                        .filter(
                            ActivitySegmentRecord.user_id == self._user_id,
                            ActivitySegmentRecord.start_time_utc >= cursor.replace(tzinfo=None),
                            ActivitySegmentRecord.start_time_utc < chunk_end.replace(tzinfo=None),
                        )
                        .delete(synchronize_session=False)
                    )
                    db.commit()

                segments = self._build_segments_for_timerange(
                    db=db,
                    user_id=self._user_id,
                    device_id=self._device_id,
                    start_time_iso=cursor.isoformat(),
                    end_time_iso=chunk_end.isoformat(),
                    os_repo=os_repo,
                    ide_repo=ide_repo,
                    browser_repo=browser_repo,
                    segment_repo=segment_repo,
                    apply_arrival_delay=False,
                )
                built += len(segments)
                chunks += 1
            except Exception:
                failed += 1
                self.logger.exception(
                    "Backfill chunk %s -> %s failed; continuing.",
                    cursor.isoformat(), chunk_end.isoformat(),
                )
                db.rollback()
            finally:
                db.close()
            cursor = chunk_end

        relinked, lost = self._relink_label_anchors(anchors)

        summary = {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "chunks": chunks,
            "chunks_failed": failed,
            "segments_purged": purged,
            "segments_built": built,
            "labels_relinked": relinked,
            "labels_lost": lost,
        }
        self.logger.info("Backfill complete: %s", summary)
        return summary

    def _snapshot_label_anchors(self, start: datetime, end: datetime) -> list[tuple[str, datetime]]:
        """Pin each label in range to the start instant of the segment it marks."""
        db: DbSession = SessionLocal()
        try:
            rows = (
                db.query(ActivitySegmentLabelRecord.id, ActivitySegmentRecord.start_time_utc)
                .join(ActivitySegmentRecord, ActivitySegmentRecord.id == ActivitySegmentLabelRecord.segment_id)
                .filter(
                    ActivitySegmentRecord.start_time_utc >= start.replace(tzinfo=None),
                    ActivitySegmentRecord.start_time_utc < end.replace(tzinfo=None),
                )
                .all()
            )
            self.logger.info("Anchored %d label(s) before purge.", len(rows))
            return [(row[0], row[1]) for row in rows]
        finally:
            db.close()

    def _relink_label_anchors(self, anchors: list[tuple[str, datetime]]) -> tuple[int, int]:
        """Re-point anchored labels at whichever rebuilt segment covers them."""
        if not anchors:
            return 0, 0
        db: DbSession = SessionLocal()
        try:
            relinked = 0
            lost = 0
            for label_id, anchor in anchors:
                segment = (
                    db.query(ActivitySegmentRecord)
                    .filter(
                        ActivitySegmentRecord.user_id == self._user_id,
                        ActivitySegmentRecord.start_time_utc <= anchor,
                        ActivitySegmentRecord.end_time_utc > anchor,
                    )
                    .order_by(ActivitySegmentRecord.start_time_utc.desc())
                    .first()
                )
                label = db.get(ActivitySegmentLabelRecord, label_id)
                if segment is None or label is None:
                    lost += 1
                    self.logger.warning(
                        "Label %s (anchored at %s) has no rebuilt segment to attach to.",
                        label_id, anchor,
                    )
                    continue
                label.segment_id = segment.id
                relinked += 1
            db.commit()
            self.logger.info("Relinked %d label(s); %d could not be placed.", relinked, lost)
            return relinked, lost
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _build_segments_for_timerange(
        self,
        db: DbSession,
        user_id: str,
        device_id: str,
        start_time_iso: str,
        end_time_iso: str,
        os_repo: OSSessionRepository,
        ide_repo: IDESessionRepository,
        browser_repo: BrowserSessionRepository,
        segment_repo: ActivitySegmentRepository,
        apply_arrival_delay: bool = True,
    ) -> list[ActivitySegmentRecord]:
        """Build activity segments for a user/device in a time range.

        This is the main entry point that implements the full pipeline:
        1. Load and normalize source data
        2. Use OS sessions as timeline spine
        3. Find overlapping IDE/browser sessions
        4. Split at meaningful boundaries
        5. Assign primary source and enrich with details
        6. Generate gap/idle/locked segments
        7. Validate no overlaps
        8. Upsert results

        Args:
            db: Database session
            user_id: User identifier
            device_id: Device identifier
            start_time_iso: Start of processing window (ISO format)
            end_time_iso: End of processing window (ISO format)
            os_repo: Repository for OS sessions
            ide_repo: Repository for IDE sessions
            browser_repo: Repository for browser sessions
            segment_repo: Repository for activity segments

        Returns:
            List of created/updated activity segments
        """
        self.logger.info(
            f"Building activity segments for user {user_id} on device {device_id} "
            f"from {start_time_iso} to {end_time_iso}"
        )

        # Step 1: Hold back the tail of the window so events still in flight are
        # not treated as absent. Backfill skips this — historical events arrived
        # long ago, and trimming every chunk would leave a hole at each seam.
        safe_end_time = (
            self._calculate_safe_processing_end(end_time_iso)
            if apply_arrival_delay else end_time_iso
        )
        if not self._is_valid_timerange(start_time_iso, safe_end_time):
            self.logger.warning(
                f"Invalid time range after applying delay: {start_time_iso} to {safe_end_time}"
            )
            return []

        # Step 2: Load source data
        os_sessions = self._load_and_normalize_os_sessions(
            db, user_id, device_id, start_time_iso, safe_end_time, os_repo
        )
        ide_sessions = self._load_and_normalize_ide_sessions(
            db, user_id, device_id, start_time_iso, safe_end_time, ide_repo
        )
        browser_sessions = self._load_and_normalize_browser_sessions(
            db, user_id, device_id, start_time_iso, safe_end_time, browser_repo
        )

        # No early return when os_sessions is empty: _generate_special_segments
        # still has to mark the window as a gap. Returning here meant a window
        # with nothing in it produced no rows at all, so an outage left a hole
        # in the timeline instead of a recorded gap.
        if not os_sessions:
            self.logger.info("No OS sessions found in time range — emitting gap coverage only")

        # Step 3: Build timeline using OS sessions as spine, clipped to the window
        timeline_segments = self._build_timeline_from_os_sessions(
            os_sessions,
            window_start=parse_iso(start_time_iso),
            window_end=parse_iso(safe_end_time),
        )

        # Step 4: Enrich with IDE and browser overlaps
        enriched_segments = self._enrich_with_overlaps(timeline_segments, ide_sessions, browser_sessions)

        # Step 5: Split at meaningful boundaries
        split_segments = self._split_at_boundaries(enriched_segments, ide_sessions, browser_sessions)

        # Step 6: Assign primary sources and enrich details
        sourced_segments = self._assign_primary_sources(split_segments, ide_sessions, browser_sessions)

        # Step 7: Generate gap, idle, and locked segments
        complete_segments = self._generate_special_segments(
            sourced_segments, os_sessions, ide_sessions, browser_sessions, start_time_iso, safe_end_time
        )

        # Step 8: Validate no temporal overlaps
        validated_segments = self._validate_no_overlaps(complete_segments)

        # Step 9: Categorize segments and calculate focus scoring metadata
        categorized_segments = []
        categorizer = Categorizer()  # Initialize categorizer for this batch
        focus_scorer = FocusScorer()
        self._attach_neighbourhood_switches(db, user_id, device_id, validated_segments)
        for seg_dict in validated_segments:
            # Resolve state once, here, and let both the categorizer and the
            # focus scorer read it off seg_dict. It used to be a local that only
            # the categorizer's throwaway record saw, so FocusScorer's
            # segment.get("state") was None for every segment ever scored —
            # idle, locked and active all landed on the same fallback.
            seg_dict["state"] = self._determine_state(seg_dict)
            temp_segment = ActivitySegmentRecord(
                title=seg_dict["text_content"].get("title"),
                detail=seg_dict["text_content"].get("detail"),
                app_name=seg_dict["text_content"].get("app_name"),
                state=seg_dict["state"],
                primary_source=seg_dict.get("primary_source", "os")
            )
            category, method, confidence = categorizer.predict(temp_segment)
            seg_dict["category"] = category
            seg_dict["category_method"] = method
            seg_dict["category_confidence"] = confidence

            # Below MIN_SCORABLE_SEC the signals are too coarse to mean anything,
            # so no score is produced. The keys are left absent rather than set
            # to None: _upsert_segments reads them with .get(key, existing), and
            # an explicit None would have overwritten a good stored score with
            # nothing every time such a segment was rebuilt.
            if seg_dict.get("duration", 0) >= MIN_SCORABLE_SEC:
                focus_score, concurrent_json, signals_json = focus_scorer.score_segment(seg_dict)
                seg_dict["focus_score"] = float(focus_score)
                seg_dict["concurrent_json"] = concurrent_json
                seg_dict["signals_json"] = signals_json

            categorized_segments.append(seg_dict)

        # Step 10: Upsert to database
        result_segments = self._upsert_segments(categorized_segments, user_id, device_id, db, segment_repo)

        self.logger.info(
            f"Built {len(result_segments)} activity segments for user {user_id} on device {device_id}"
        )
        return result_segments

    # Remaining helper methods remain largely the same but adjusted to accept dependencies
    # where needed...

    def _calculate_safe_processing_end(self, end_time_iso: str) -> str:
        """Calculate the safe end time accounting for event arrival delay.

        Args:
            end_time_iso: Original end time in ISO format

        Returns:
            Adjusted end time accounting for delayed events
        """
        end_dt = parse_iso(end_time_iso)
        # Convert to UTC for calculation, then back to local time
        if hasattr(end_dt, 'utcoffset') and end_dt.utcoffset() is not None:
            utc_time = end_dt.astimezone(timezone.utc)
        else:
            # Assume UTC if no timezone info
            utc_time = end_dt.replace(tzinfo=timezone.utc)

        # Subtract the delay
        safe_utc = utc_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)

        # The ternary here was inverted: safe_local is always a datetime, so the
        # hasattr check always passed and this always returned local_now_iso(),
        # throwing away both the caller's end time and the arrival-delay guard
        # it had just computed. That also silently widened every backfill window
        # to "now".
        return to_local_iso(safe_utc)

    def _is_valid_timerange(self, start_iso: str, end_iso: str) -> bool:
        """Check if the time range is valid (start before end).

        Args:
            start_iso: Start time in ISO format
            end_iso: End time in ISO format

        Returns:
            True if start < end, False otherwise
        """
        try:
            start_dt = parse_iso(start_iso)
            end_dt = parse_iso(end_iso)
            return start_dt < end_dt
        except Exception:
            return False

    def _load_and_normalize_os_sessions(
        self,
        db: DbSession,
        user_id: str,
        device_id: str,
        start_iso: str,
        end_iso: str,
        os_repo: OSSessionRepository,
    ) -> list[OSSessionRecord]:
        """Load and normalize OS sessions.

        Args:
            db: Database session
            user_id: User identifier
            device_id: Device identifier
            start_iso: Start time in ISO format
            end_iso: End time in ISO format
            os_repo: Repository for OS sessions

        Returns:
            List of normalized OS sessions
        """
        sessions = os_repo.get_sessions_overlapping_db(db, user_id, start_iso, end_iso)
        return self._normalize_sessions(sessions, "os")

    def _load_and_normalize_ide_sessions(
        self,
        db: DbSession,
        user_id: str,
        device_id: str,
        start_iso: str,
        end_iso: str,
        ide_repo: IDESessionRepository,
    ) -> list[IDESessionRecord]:
        """Load and normalize IDE sessions.

        Args:
            db: Database session
            user_id: User identifier
            device_id: Device identifier
            start_iso: Start time in ISO format
            end_iso: End time in ISO format
            ide_repo: Repository for IDE sessions

        Returns:
            List of normalized IDE sessions
        """
        # Overlap, not start-membership — see
        # IDESessionRepository.get_sessions_overlapping_db. get_all_sessions_db
        # only returned sessions starting inside this window, so any coding
        # block longer than one build tick was invisible here and the segments
        # covering it were never linked to their IDE session.
        sessions = ide_repo.get_sessions_overlapping_db(db, user_id, start_iso, end_iso)
        return self._normalize_sessions(sessions, "ide")

    def _load_and_normalize_browser_sessions(
        self,
        db: DbSession,
        user_id: str,
        device_id: str,
        start_iso: str,
        end_iso: str,
        browser_repo: BrowserSessionRepository,
    ) -> list[BrowserSessionRecord]:
        """Load and normalize browser sessions.

        Args:
            db: Database session
            user_id: User identifier
            device_id: Device identifier
            start_iso: Start time in ISO format
            end_iso: End time in ISO format
            browser_repo: Repository for browser sessions

        Returns:
            List of normalized browser sessions
        """
        # Overlap, not start-membership — same reason as the IDE loader above.
        sessions = browser_repo.get_sessions_overlapping_db(
            db, user_id, start_iso, end_iso
        )
        return self._normalize_sessions(sessions, "browser")

    def _normalize_sessions(
        self,
        sessions: list,
        source_type: str,
    ) -> list:
        """Normalize session objects to have consistent datetime attributes.

        Args:
            sessions: List of session objects (OSSessionRecord, etc.)
            source_type: Type of source ("os", "ide", "browser")

        Returns:
            List of sessions with normalized datetime attributes
        """
        # In practice, we work with the existing objects but ensure
        # datetime parsing is consistent in our usage
        return sessions

    def _build_timeline_from_os_sessions(
        self,
        os_sessions: list[OSSessionRecord],
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[dict]:
        """Build initial timeline segments from OS sessions.

        Args:
            os_sessions: List of OS sessions
            window_start: Clip segments to this lower bound (optional)
            window_end: Clip segments to this upper bound (optional)

        Returns:
            List of timeline segment dictionaries
        """
        timeline = []
        for session in os_sessions:
            # Parse session times
            try:
                start_time = parse_iso(session.session_start)
                end_time = parse_iso(session.session_end) if session.session_end else None
            except Exception as e:
                self.logger.warning(f"Failed to parse session times: {e}")
                continue

            if not end_time:
                # Ongoing session. Its true end is unknown, so cover it only as
                # far as the evidence goes: not past the window, not past the
                # present, and not more than one segment's length past its own
                # start. local_now() (not utcnow) so it is comparable with the
                # parsed, timezone-pinned session times.
                #
                # Both bounds are load-bearing, and only a backfill exposed
                # them. A live tick ends its window at roughly now and runs
                # every 5 minutes, so an open session was never stretched far;
                # a backfill takes an arbitrary range and revisits it once.
                # Running one over 2026-08-10 stretched a still-open session to
                # midnight, 9.4 h of fabricated coverage. Clamping to now was
                # not enough on its own: an open row is also how this tracker
                # records a session it never got to close, so the Code session
                # left open at 14:38 by a suspend claimed the six hours until
                # the machine woke. A genuinely live session is at most one
                # poll old, and segments are cut at MAX_SEGMENT_SEC anyway, so
                # a stale row can now contribute at most that.
                now = local_now()
                bound = start_time + timedelta(seconds=MAX_SEGMENT_SEC)
                end_time = min(window_end, now, bound) if window_end else min(now, bound)

            # Sessions are now loaded by overlap, so a multi-hour session can
            # arrive whole in a 5-minute window. Clip it, or one tick would
            # write a segment covering hours it has no business claiming and
            # the next tick would overlap it.
            if window_start is not None:
                start_time = max(start_time, window_start)
            if window_end is not None:
                end_time = min(end_time, window_end)
            if end_time <= start_time:
                continue

            # Determine title: prefer window_title, fallback to app_name, then "Unknown"
            window_title = getattr(session, 'window_title', '') or ''
            if not window_title:
                window_title = getattr(session, 'app_name', '') or 'Unknown'
            # Ensure we have a valid time range (end after start)
            if end_time <= start_time:
                # If zero or negative duration, push end forward by 1 second
                end_time = start_time + timedelta(seconds=1)
            # Create base segment
            segment = {
                "start_time": start_time,
                "end_time": end_time,
                "duration": (end_time - start_time).total_seconds(),
                "os_session_ids": [session.id],
                "ide_session_ids": [],
                "browser_session_ids": [],
                "sources": {
                    "os": [session],
                    "ide": [],
                    "browser": [],
                },
                "text_content": {
                    "app_name": getattr(session, 'app_name', ''),
                    "title": window_title,
                    "detail": "",
                }
            }
            timeline.append(segment)

        return timeline

    def _enrich_with_overlaps(
        self,
        timeline_segments: list[dict],
        ide_sessions: list[IDESessionRecord],
        browser_sessions: list[BrowserSessionRecord],
    ) -> list[dict]:
        """Enrich timeline segments with overlapping IDE and browser sessions.

        Args:
            timeline_segments: Base timeline segments from OS sessions
            ide_sessions: IDE sessions to check for overlap
            browser_sessions: Browser sessions to check for overlap

        Returns:
            Timeline segments with overlapping sessions attached
        """
        for segment in timeline_segments:
            seg_start = segment["start_time"]
            seg_end = segment["end_time"]

            # Check for overlapping IDE sessions
            for ide_session in ide_sessions:
                try:
                    ide_start = parse_iso(ide_session.session_start)
                    ide_end = parse_iso(ide_session.session_end) if ide_session.session_end else None
                    if not ide_end:
                        ide_end = datetime.now(timezone.utc)

                    # Check for overlap: start_A < end_B and end_A > start_B
                    if ide_start < seg_end and ide_end > seg_start:
                        segment["ide_session_ids"].append(ide_session.id)
                        segment["sources"]["ide"].append(ide_session)

                        # Extract text content for enrichment
                        if hasattr(ide_session, 'app_name') and ide_session.app_name:
                            if not segment["text_content"]["app_name"]:
                                segment["text_content"]["app_name"] = ide_session.app_name
                        if hasattr(ide_session, 'workspace_name') and ide_session.workspace_name:
                            if not segment["text_content"].get("title"):
                                segment["text_content"]["title"] = ide_session.workspace_name
                except Exception as e:
                    self.logger.debug(f"Error processing IDE session overlap: {e}")
                    continue

            # Check for overlapping browser sessions
            for browser_session in browser_sessions:
                try:
                    browser_start = parse_iso(browser_session.session_start)
                    browser_end = parse_iso(browser_session.session_end) if browser_session.session_end else None
                    if not browser_end:
                        browser_end = datetime.now(timezone.utc)

                    # Check for overlap
                    if browser_start < seg_end and browser_end > seg_start:
                        segment["browser_session_ids"].append(browser_session.id)
                        segment["sources"]["browser"].append(browser_session)

                        # Extract text content for enrichment
                        if hasattr(browser_session, 'browser_name') and browser_session.browser_name:
                            if not segment["text_content"]["app_name"]:
                                segment["text_content"]["app_name"] = browser_session.browser_name
                        if hasattr(browser_session, 'title') and browser_session.title:
                            if not segment["text_content"]["title"]:
                                segment["text_content"]["title"] = browser_session.title
                        if hasattr(browser_session, 'url') and browser_session.url:
                            if not segment["text_content"]["detail"]:
                                segment["text_content"]["detail"] = browser_session.url
                except Exception as e:
                    self.logger.debug(f"Error processing browser session overlap: {e}")
                    continue

        return timeline_segments

    def _split_at_boundaries(
        self,
        segments: list[dict],
        ide_sessions: list[IDESessionRecord],
        browser_sessions: list[BrowserSessionRecord],
    ) -> list[dict]:
        """Split segments at meaningful boundaries (IDE/browser start/end, etc.).

        Args:
            segments: Segments to potentially split
            ide_sessions: IDE sessions for boundary detection
            browser_sessions: Browser sessions for boundary detection

        Returns:
            List of segments, potentially split into smaller pieces
        """
        all_boundaries = []

        # Collect all potential boundary points
        for segment in segments:
            all_boundaries.append(segment["start_time"])
            all_boundaries.append(segment["end_time"])

        # Add IDE session boundaries
        for session in ide_sessions:
            try:
                start = parse_iso(session.session_start)
                end = parse_iso(session.session_end) if session.session_end else None
                if end:
                    all_boundaries.extend([start, end])
                else:
                    all_boundaries.append(start)  # Only start if no end
            except Exception:
                continue

        # Add browser session boundaries
        for session in browser_sessions:
            try:
                start = parse_iso(session.session_start)
                end = parse_iso(session.session_end) if session.session_end else None
                if end:
                    all_boundaries.extend([start, end])
                else:
                    all_boundaries.append(start)
            except Exception:
                continue

        # Cut long stretches at regular intervals too. Now that sessions load by
        # overlap, a single uninterrupted focus block can span hours; without
        # these the timeline would carry one enormous row for it.
        for segment in segments:
            cursor = segment["start_time"] + timedelta(seconds=MAX_SEGMENT_SEC)
            while cursor < segment["end_time"]:
                all_boundaries.append(cursor)
                cursor += timedelta(seconds=MAX_SEGMENT_SEC)

        # Sort and deduplicate boundaries
        unique_boundaries = sorted(list(set(all_boundaries)))

        # Split each segment at the boundaries
        split_segments = []
        for segment in segments:
            seg_start = segment["start_time"]
            seg_end = segment["end_time"]

            # Find boundaries that fall within this segment
            internal_boundaries = [
                b for b in unique_boundaries
                if seg_start < b < seg_end
            ]

            if not internal_boundaries:
                # No internal boundaries, keep segment as-is
                split_segments.append(segment)
            else:
                # Split the segment at each boundary
                split_points = [seg_start] + internal_boundaries + [seg_end]
                for i in range(len(split_points) - 1):
                    sub_start = split_points[i]
                    sub_end = split_points[i + 1]

                    # Skip zero-length segments
                    if sub_start >= sub_end:
                        continue

                    # Create sub-segment inheriting properties from parent
                    sub_segment = {
                        "start_time": sub_start,
                        "end_time": sub_end,
                        "duration": (sub_end - sub_start).total_seconds(),
                        "os_session_ids": segment["os_session_ids"].copy(),
                        "ide_session_ids": segment["ide_session_ids"].copy(),
                        "browser_session_ids": segment["browser_session_ids"].copy(),
                        "sources": {
                            "os": segment["sources"]["os"].copy(),
                            "ide": segment["sources"]["ide"].copy(),
                            "browser": segment["sources"]["browser"].copy(),
                        },
                        "text_content": segment["text_content"].copy(),
                    }
                    split_segments.append(sub_segment)

        return split_segments

    def _assign_primary_sources(
        self,
        segments: list[dict],
        ide_sessions: list[IDESessionRecord],
        browser_sessions: list[BrowserSessionRecord],
    ) -> list[dict]:
        """Assign primary source to each segment based on overlap and relevance.

        Args:
            segments: Segments to assign primary sources to
            ide_sessions: IDE sessions for reference
            browser_sessions: Browser sessions for reference

        Returns:
            Segments with primary_source assigned
        """
        def overlap_sec(session, segment: dict) -> float:
            """Seconds ``session`` covers of ``segment``.

            A session that is still open covers the segment to its end. The
            previous version required ``session_end`` and skipped open ones
            entirely, scoring them zero — which mattered once the loaders
            started returning open sessions at all.
            """
            if not session.session_start:
                return 0.0
            try:
                s_start = parse_iso(session.session_start)
                s_end = (
                    parse_iso(session.session_end)
                    if session.session_end else segment["end_time"]
                )
            except Exception:
                return 0.0
            return max(
                0.0,
                (
                    min(segment["end_time"], s_end)
                    - max(segment["start_time"], s_start)
                ).total_seconds(),
            )

        def is_foreground(session) -> bool:
            """Was this session what the user was actually looking at?

            OS sessions carry no such flag — the OS spine is foreground by
            definition — so a missing attribute means yes.
            """
            flag = getattr(session, "is_foreground", None)
            return True if flag is None else bool(flag)

        for segment in segments:
            # Calculate overlap scores for each source type present.
            #
            # Background sessions are excluded from the scoring but stay linked
            # in ``sources``: an AI agent editing in a blurred window is real
            # IDE data worth keeping, it just is not what the user was doing.
            # Counting it here let a background editor outscore the foreground
            # app it was sitting behind — with the 1.5x boost below, an IDE
            # session merely open across a browsing segment took the segment
            # from it. 716 s of one day's browser and media time was claimed by
            # the IDE that way.
            scores = {
                source: sum(
                    overlap_sec(s, segment)
                    for s in segment["sources"][source]
                    if is_foreground(s)
                )
                for source in ("os", "ide", "browser")
            }

            # Determine primary source based on highest overlap
            # But apply heuristics: IDE/browser get boost for active work
            if scores["ide"] > 0:
                scores["ide"] *= 1.5  # Boost IDE as it often indicates productive work
            if scores["browser"] > 0:
                scores["browser"] *= 1.2  # Smaller boost for browser

            if scores:
                primary_source = max(scores, key=scores.get)
                # Only assign non-OS source if it has significant overlap
                if primary_source != "os" and scores[primary_source] < 60:  # Less than 1 minute
                    primary_source = "os"

                segment["primary_source"] = primary_source
            else:
                # Fallback to OS
                segment["primary_source"] = "os"

        return segments

    def _generate_special_segments(
        self,
        segments: list[dict],
        os_sessions: list[OSSessionRecord],
        ide_sessions: list[IDESessionRecord],
        browser_sessions: list[BrowserSessionRecord],
        start_time_iso: str,
        end_time_iso: str,
    ) -> list[dict]:
        """Generate gap, idle, and locked segments where appropriate.

        Args:
            segments: Current segments to potentially fill gaps in
            os_sessions: OS sessions for idle/lock detection
            ide_sessions: IDE sessions (not directly used here)
            browser_sessions: Browser sessions (not directly used here)
            start_time_iso: Start of overall period
            end_time_iso: End of overall period

        Returns:
            Original segments plus any generated gap/idle/locked segments
        """
        # Gap synthesis is off by default so segments never claim more time than
        # the os_sessions they derive from — see EMIT_GAP_SEGMENTS. Idle time is
        # not a gap: it arrives as state='idle' on a real OS-backed segment.
        if not EMIT_GAP_SEGMENTS:
            return segments

        # Sort segments by start time
        sorted_segments = sorted(segments, key=lambda s: s["start_time"])

        # Generate gaps between segments
        filled_segments = []
        prev_end = parse_iso(start_time_iso)

        for segment in sorted_segments:
            curr_start = segment["start_time"]

            # Check for gap between previous segment and current one
            if prev_end < curr_start:
                gap_duration = (curr_start - prev_end).total_seconds()
                if gap_duration > 30:  # Only create gap segments for gaps > 30 seconds
                    gap_segment = {
                        "start_time": prev_end,
                        "end_time": curr_start,
                        "duration": gap_duration,
                        "os_session_ids": [],
                        "ide_session_ids": [],
                        "browser_session_ids": [],
                        "sources": {"os": [], "ide": [], "browser": []},
                        "text_content": {"app_name": "", "title": "", "detail": ""},
                        "primary_source": "synthetic",
                        "is_gap": True,  # Mark for special handling
                    }
                    filled_segments.append(gap_segment)

            # Add the current segment
            filled_segments.append(segment)
            prev_end = segment["end_time"]

        # Check for trailing gap after last segment
        end_time = parse_iso(end_time_iso)
        if prev_end < end_time:
            gap_duration = (end_time - prev_end).total_seconds()
            if gap_duration > 30:
                gap_segment = {
                    "start_time": prev_end,
                    "end_time": end_time,
                    "duration": gap_duration,
                    "os_session_ids": [],
                    "ide_session_ids": [],
                    "browser_session_ids": [],
                    "sources": {"os": [], "ide": [], "browser": []},
                    "text_content": {"app_name": "", "title": "", "detail": ""},
                    "primary_source": "synthetic",
                    "is_gap": True,
                }
                filled_segments.append(gap_segment)

        # TODO: Add idle and locked segment detection based on OS session state
        # For now, we'll rely on the state field being set during enrichment

        return filled_segments

    def _validate_no_overlaps(
        self,
        segments: list[dict],
    ) -> list[dict]:
        """Validate that no segments overlap and merge or adjust if needed.

        Args:
            segments: Segments to validate

        Returns:
            Validated list of non-overlapping segments
        """
        if not segments:
            return segments

        # Sort by start time
        sorted_segments = sorted(segments, key=lambda s: s["start_time"])

        validated = [sorted_segments[0]]

        for i in range(1, len(sorted_segments)):
            current = sorted_segments[i]
            previous = validated[-1]

            # Check for overlap: current.start < previous.end
            if current["start_time"] < previous["end_time"]:
                self.logger.warning(
                    f"Overlap detected: previous ends at {previous['end_time']}, "
                    f"current starts at {current['start_time']}"
                )

                # Strategy: truncate previous segment to end at current start
                # Alternative: could merge or adjust both
                overlap_duration = (previous["end_time"] - current["start_time"]).total_seconds()
                if overlap_duration > 60:  # Only log if significant overlap (>1 min)
                    self.logger.warning(
                        f"Significant overlap of {overlap_duration} seconds between segments"
                    )

                # Adjust previous segment to end when current starts
                previous["end_time"] = current["start_time"]
                previous["duration"] = max(0, (previous["end_time"] - previous["start_time"]).total_seconds())

                # If this makes the previous segment too short, consider removing it
                if previous["duration"] < 10:  # Less than 10 seconds
                    # Remove the previous segment and merge with current
                    validated.pop()
                    # Merge: extend current back to previous start
                    current["start_time"] = previous["start_time"]
                    # Merge sources and text content (simplified)
                    current["os_session_ids"] = list(
                        set(previous["os_session_ids"] + current["os_session_ids"])
                    )
                    current["ide_session_ids"] = list(
                        set(previous["ide_session_ids"] + current["ide_session_ids"])
                    )
                    current["browser_session_ids"] = list(
                        set(previous["browser_session_ids"] + current["browser_session_ids"])
                    )
                    # Recalculate duration
                    current["duration"] = (
                        current["end_time"] - current["start_time"]
                    ).total_seconds()

            # Add current (possibly adjusted) segment
            validated.append(current)

        return validated

    def _upsert_segments(
        self,
        segments: list[dict],
        user_id: str,
        device_id: str,
        db: DbSession,
        segment_repo: ActivitySegmentRepository,
    ) -> list[ActivitySegmentRecord]:
        """Insert or update segments in the database.

        Args:
            segments: Segment dictionaries to persist
            user_id: User identifier
            device_id: Device identifier
            db: Database session
            segment_repo: Repository for activity segments

        Returns:
            List of created/updated ActivitySegmentRecord objects
        """
        result = []

        for seg_dict in segments:
            # Check if a segment with the same user_id, device_id, start_time_utc, and end_time_utc already exists
            existing = db.query(ActivitySegmentRecord).filter(
                ActivitySegmentRecord.user_id == user_id,
                ActivitySegmentRecord.device_id == device_id,
                ActivitySegmentRecord.start_time_utc == seg_dict["start_time"],
                ActivitySegmentRecord.end_time_utc == seg_dict["end_time"]
            ).first()

            if existing:
                # Update existing record
                existing.schema_version = 3  # Match current SCHEMA_VERSION from config
                existing.duration_sec = int(max(0, seg_dict["duration"]))
                existing.timezone_name = "Asia/Colombo"  # Should come from config
                existing.local_date = seg_dict["start_time"].date().isoformat()
                existing.primary_source = seg_dict.get("primary_source", "os")
                existing.app_name = seg_dict["text_content"].get("app_name") or None
                existing.title = seg_dict["text_content"].get("title") or None
                existing.detail = seg_dict["text_content"].get("detail") or None
                existing.state = seg_dict.get("state") or self._determine_state(seg_dict)
                existing.os_session_id = seg_dict["os_session_ids"][0] if seg_dict["os_session_ids"] else None
                existing.ide_session_id = seg_dict["ide_session_ids"][0] if seg_dict["ide_session_ids"] else None
                existing.browser_session_id = seg_dict["browser_session_ids"][0] if seg_dict["browser_session_ids"] else None
                # Note: These are simplified - in reality we might want to store
                # multiple IDs or use a junction table for many-to-many
                # A category someone assigned by hand outranks anything the
                # classifier has to say, and rebuilds are routine — without
                # this guard every correction survives only until the next
                # build pass rewrites these three columns.
                if existing.category_method != "user":
                    existing.category = seg_dict.get("category")
                    existing.category_method = seg_dict.get("category_method")
                    existing.category_confidence = seg_dict.get("category_confidence")
                existing.focus_score = seg_dict.get("focus_score", existing.focus_score)
                existing.concurrent_json = seg_dict.get("concurrent_json", existing.concurrent_json)
                existing.signals_json = seg_dict.get("signals_json", existing.signals_json)
                existing.embedding_status = seg_dict.get("embedding_status", existing.embedding_status)
                existing.sync_status = seg_dict.get("sync_status", existing.sync_status)

                result.append(existing)
            else:
                # Create new record
                # Generate a unique ID for this segment
                # In a production system, we might use a deterministic UUID based on content
                import uuid
                segment_id = str(uuid.uuid4())

                segment_record = ActivitySegmentRecord(
                    id=segment_id,
                    user_id=user_id,
                    device_id=device_id,
                    schema_version=3,  # Match current SCHEMA_VERSION from config
                    start_time_utc=seg_dict["start_time"],
                    end_time_utc=seg_dict["end_time"],
                    duration_sec=int(max(0, seg_dict["duration"])),
                    timezone_name="Asia/Colombo",  # Should come from config
                    local_date=seg_dict["start_time"].date().isoformat(),
                    primary_source=seg_dict.get("primary_source", "os"),
                    app_name=seg_dict["text_content"].get("app_name") or None,
                    title=seg_dict["text_content"].get("title") or None,
                    detail=seg_dict["text_content"].get("detail") or None,
                    state=seg_dict.get("state") or self._determine_state(seg_dict),
                    os_session_id=seg_dict["os_session_ids"][0] if seg_dict["os_session_ids"] else None,
                    ide_session_id=seg_dict["ide_session_ids"][0] if seg_dict["ide_session_ids"] else None,
                    browser_session_id=seg_dict["browser_session_ids"][0] if seg_dict["browser_session_ids"] else None,
                    # Note: These are simplified - in reality we might want to store
                    # multiple IDs or use a junction table for many-to-many
                    category=seg_dict.get("category"),
                    category_method=seg_dict.get("category_method"),
                    category_confidence=seg_dict.get("category_confidence"),
                    focus_score=seg_dict.get("focus_score"),
                    concurrent_json=seg_dict.get("concurrent_json"),
                    signals_json=seg_dict.get("signals_json"),
                    embedding_status="pending",
                    sync_status="pending",
                )

                # Add to session
                db.add(segment_record)
                result.append(segment_record)

        # Commit all changes
        try:
            db.commit()
            for record in result:
                db.refresh(record)
        except Exception as e:
            db.rollback()
            self.logger.error(f"Failed to persist activity segments: {e}")
            raise

        return result

    def _attach_neighbourhood_switches(
        self,
        db: DbSession,
        user_id: str,
        device_id: str,
        segments: list[dict],
    ) -> None:
        """Set the timeline switch rate on each segment before it is scored.

        A tick only holds the few minutes it just built, but the window the rate
        is measured over is wider than that, so the segments at the start of a
        tick would see a truncated neighbourhood and look artificially calm. Rows
        already persisted just before the window are pulled back in as context —
        they are not rescored, they only supply boundaries.
        """
        if not segments:
            return

        window = timedelta(seconds=NEIGHBOURHOOD_WINDOW_SEC)
        earliest = min(seg["start_time"] for seg in segments)
        latest = max(seg["end_time"] for seg in segments)

        context: list[tuple] = []
        try:
            rows = (
                db.query(
                    ActivitySegmentRecord.start_time_utc,
                    ActivitySegmentRecord.end_time_utc,
                    ActivitySegmentRecord.app_name,
                )
                .filter(
                    ActivitySegmentRecord.user_id == user_id,
                    ActivitySegmentRecord.device_id == device_id,
                    ActivitySegmentRecord.start_time_utc >= (earliest - window).replace(tzinfo=None),
                    ActivitySegmentRecord.start_time_utc < latest.replace(tzinfo=None),
                )
                .all()
            )
            for start, end, app_name in rows:
                start = start if start.tzinfo else start.replace(tzinfo=earliest.tzinfo)
                end = end if end.tzinfo else end.replace(tzinfo=earliest.tzinfo)
                context.append((start, end, app_name))
        except Exception:
            # Context is an accuracy improvement, not a precondition. Losing it
            # narrows the window for the first segments of a tick; failing the
            # whole build over it would cost the segments themselves.
            self.logger.exception(
                "Could not load neighbourhood context; scoring from this tick alone."
            )
            context = []

        timeline = [
            (seg["start_time"], seg["end_time"], seg["text_content"].get("app_name"))
            for seg in segments
        ] + context

        rates = neighbourhood_switch_rates(timeline)
        for seg, rate in zip(segments, rates):
            seg[FocusScorer.NEIGHBOURHOOD_KEY] = rate

    def _determine_state(self, segment: dict) -> str:
        """Determine the state (active, idle, locked, gap) for a segment.

        Taken from the OS session the segment actually overlaps most. This used
        to return "active" unconditionally with a "for now" note, so idle time
        was indistinguishable from work: 47.8 h of the 81.5 h recorded for
        2026-07-21..28 was marked active while its OS session said idle, and
        'idle' had never once been written to the table despite the schema
        allowing it since 0006.

        Args:
            segment: Segment dictionary

        Returns:
            One of: 'active', 'idle', 'locked', 'gap'
        """
        # Check if explicitly marked as gap
        if segment.get("is_gap", False):
            return "gap"

        os_sessions = segment.get("sources", {}).get("os") or []
        if not os_sessions:
            return "active"

        # A segment can straddle more than one OS session after splitting, so
        # attribute it to whichever one covers the most of it rather than to
        # whichever happens to be first.
        best_state = None
        best_overlap = -1.0
        for session in os_sessions:
            state = getattr(session, "state", None)
            if not state:
                continue
            try:
                s_start = parse_iso(session.session_start)
                s_end = (
                    parse_iso(session.session_end)
                    if session.session_end else segment["end_time"]
                )
            except Exception:
                continue
            overlap = (
                min(segment["end_time"], s_end) - max(segment["start_time"], s_start)
            ).total_seconds()
            if overlap > best_overlap:
                best_overlap = overlap
                best_state = state

        if best_state in ("active", "idle", "locked"):
            return best_state
        return "active"

    def run_once(self) -> str:
        """Run one build cycle immediately (for debug routes and manual triggers).

        Deliberately the same code path as a scheduled tick, so a manual run
        cannot succeed while the real thing is broken. Note it still cannot
        reprocess history — the watermark only ever moves forward. Use
        :meth:`backfill` for that.

        Returns:
            Status message
        """
        try:
            self._build_recent_segments()
            return "OK"
        except Exception as exc:
            self.logger.exception("Error in ActivitySegmentBuilder.run_once")
            return f"Error: {exc}"

    # Helper methods to match the interface used in other services
    def local_now_iso(self) -> str:
        """Get current local time as ISO string."""
        from app.core.time import local_now_iso
        return local_now_iso()

    def parse_iso(self, value: str):
        """Parse ISO string to datetime."""
        from app.core.time import parse_iso
        return parse_iso(value)