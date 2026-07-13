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
from app.models.db import ActivitySegmentRecord
from app.models.db import BrowserSessionRecord
from app.models.db import IDESessionRecord
from app.models.db import OSSessionRecord
from app.repositories.activity_segment_repository import ActivitySegmentRepository
from app.repositories.browser_session_repository import BrowserSessionRepository
from app.repositories.ide_session_repository import IDESessionRepository
from app.repositories.os_session_repository import OSSessionRepository
from app.services.categorizer import Categorizer
from app.services.focus_scorer import FocusScorer
from app.services.embedder import embedder

logger = logging.getLogger(__name__)

# How often the background thread wakes up to build segments.
BUILD_INTERVAL_SEC: int = 300  # 5 minutes

# How long to wait for delayed events before processing.
EVENT_ARRIVAL_DELAY_SECONDS: int = 30


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
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Start the recurring background timer."""
        if self._running:
            self.logger.warning("ActivitySegmentBuilder already running — ignoring start().")
            return
        self._running = True
        self.logger.info(
            "ActivitySegmentBuilder started (interval=%ds).",
            BUILD_INTERVAL_SEC,
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
        self._timer = threading.Timer(BUILD_INTERVAL_SEC, self._tick)
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

    def _build_recent_segments(self) -> None:
        """Build activity segments for a recent time window."""
        db: DbSession = SessionLocal()
        try:
            # Calculate time window: end now, start from one interval ago
            end_time = local_now()
            start_time = end_time - timedelta(seconds=BUILD_INTERVAL_SEC)

            # Apply event arrival delay to end time
            safe_end_time = end_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)

            if start_time >= safe_end_time:
                self.logger.warning(
                    f"Invalid time range after applying delay: {start_time.isoformat()} to {safe_end_time.isoformat()}"
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
                end_time_iso=safe_end_time.isoformat(),
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

        # Step 1: Apply event arrival delay to get safe processing window
        safe_end_time = self._calculate_safe_processing_end(end_time_iso)
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

        if not os_sessions:
            self.logger.info("No OS sessions found in time range")
            return []

        # Step 3: Build timeline using OS sessions as spine
        timeline_segments = self._build_timeline_from_os_sessions(os_sessions)

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
        for seg_dict in validated_segments:
            state = "gap" if seg_dict.get("is_gap", False) else "active"
            temp_segment = ActivitySegmentRecord(
                title=seg_dict["text_content"].get("title"),
                detail=seg_dict["text_content"].get("detail"),
                app_name=seg_dict["text_content"].get("app_name"),
                state=state,
                primary_source=seg_dict.get("primary_source", "os")
            )
            category, method, confidence = categorizer.predict(temp_segment)
            seg_dict["category"] = category
            seg_dict["category_method"] = method
            seg_dict["category_confidence"] = confidence

            if seg_dict.get("duration", 0) >= 5:
                focus_score, concurrent_json, signals_json = focus_scorer.score_segment(seg_dict)
                seg_dict["focus_score"] = float(focus_score)
                seg_dict["concurrent_json"] = concurrent_json
                seg_dict["signals_json"] = signals_json
            else:
                seg_dict["focus_score"] = None
                seg_dict["concurrent_json"] = None
                seg_dict["signals_json"] = None

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

        # Subscribe the delay
        safe_utc = utc_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)

        # Convert back to local time
        if hasattr(safe_utc, 'tzinfo'):
            safe_local = safe_utc.astimezone()
        else:
            # Assume local timezone
            safe_local = safe_utc.replace(tzinfo=timezone.utc).astimezone()

        return local_now_iso() if hasattr(safe_local, 'isoformat') else safe_local.isoformat()

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
        sessions = os_repo.get_completed_sessions_db(db, user_id, start_iso, end_iso)
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
        sessions = ide_repo.get_all_sessions_db(db, user_id, start_iso, end_iso)
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
        sessions = browser_repo.get_all_sessions_db(db, user_id, start_iso, end_iso)
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
    ) -> list[dict]:
        """Build initial timeline segments from OS sessions.

        Args:
            os_sessions: List of OS sessions

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
                # Ongoing session - use current time or skip
                end_time = datetime.now(timezone.utc)

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
        for segment in segments:
            # Calculate overlap scores for each source type present
            scores = {}

            # OS overlap score (always present if we got here)
            os_duration = sum(
                (min(segment["end_time"], parse_iso(s.session_end)) - max(segment["start_time"], parse_iso(s.session_start))).total_seconds()
                for s in segment["sources"]["os"]
                if s.session_start and s.session_end
            )
            scores["os"] = max(0, os_duration)

            # IDE overlap score
            ide_duration = sum(
                (min(segment["end_time"], parse_iso(s.session_end)) - max(segment["start_time"], parse_iso(s.session_start))).total_seconds()
                for s in segment["sources"]["ide"]
                if s.session_start and s.session_end
            )
            scores["ide"] = max(0, ide_duration)

            # Browser overlap score
            browser_duration = sum(
                (min(segment["end_time"], parse_iso(s.session_end)) - max(segment["start_time"], parse_iso(s.session_start))).total_seconds()
                for s in segment["sources"]["browser"]
                if s.session_start and s.session_end
            )
            scores["browser"] = max(0, browser_duration)

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
        if not segments:
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
                existing.state = self._determine_state(seg_dict)
                existing.os_session_id = seg_dict["os_session_ids"][0] if seg_dict["os_session_ids"] else None
                existing.ide_session_id = seg_dict["ide_session_ids"][0] if seg_dict["ide_session_ids"] else None
                existing.browser_session_id = seg_dict["browser_session_ids"][0] if seg_dict["browser_session_ids"] else None
                # Note: These are simplified - in reality we might want to store
                # multiple IDs or use a junction table for many-to-many
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
                    state=self._determine_state(seg_dict),
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

    def _determine_state(self, segment: dict) -> str:
        """Determine the state (active, idle, locked, gap) for a segment.

        Args:
            segment: Segment dictionary

        Returns:
            One of: 'active', 'idle', 'locked', 'gap'
        """
        # Check if explicitly marked as gap
        if segment.get("is_gap", False):
            return "gap"

        # Check source sessions for idle/locked state
        # This would examine the actual OS session state
        # For now, default to active
        return "active"

    def start(self, user_id: str = "local_user", device_id: str = "", interval_seconds: int = 300) -> None:
        """Start the activity segment builder as a periodic background job.

        Args:
            user_id: User identifier to process segments for
            device_id: Device identifier to process segments for (empty for current device)
            interval_seconds: How often to run the builder (default 5 minutes)
        """
        if hasattr(self, '_running') and self._running:
            self.logger.warning("ActivitySegmentBuilder already running — ignoring start().")
            return

        self._user_id = user_id
        self._device_id = device_id or self._get_device_id()
        self._interval_seconds = interval_seconds
        self._running = True
        self._timer = None

        self.logger.info(
            f"ActivitySegmentBuilder started (interval={interval_seconds}s, user={user_id}, device={self._device_id})."
        )
        self._schedule()

    def stop(self) -> None:
        """Stop the activity segment builder background job."""
        if not hasattr(self, '_running') or not self._running:
            return

        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self.logger.info("ActivitySegmentBuilder stopped.")

    def run_once(self) -> str:
        """Run the builder once immediately (for testing/debug routes).

        Returns:
            Status message
        """
        db: DbSession = SessionLocal()
        try:
            # Calculate time window: end now, start from one interval ago
            end_time = local_now()
            start_time = end_time - timedelta(seconds=self._interval_seconds)

            # Apply event arrival delay to end time
            safe_end_time = end_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)

            if start_time >= safe_end_time:
                self.logger.warning(
                    f"Invalid time range after applying delay: {start_time.isoformat()} to {safe_end_time.isoformat()}"
                )
                return "Skipped: invalid time range"

            # Initialize repositories with current database session
            os_repo = OSSessionRepository()
            ide_repo = IDESessionRepository()
            browser_repo = BrowserSessionRepository()
            segment_repo = ActivitySegmentRepository()

            self._build_segments_for_timerange(
                db=db,
                user_id=self._user_id,
                device_id=self._device_id,
                start_time_iso=start_time.isoformat(),
                end_time_iso=safe_end_time.isoformat(),
                os_repo=os_repo,
                ide_repo=ide_repo,
                browser_repo=browser_repo,
                segment_repo=segment_repo,
            )
            return "OK"
        except Exception as e:
            self.logger.error(f"Error in ActivitySegmentBuilder.run_once: {e}")
            return f"Error: {e}"
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _schedule(self) -> None:
        """Schedule the next tick."""
        if not self._running:
            return
        self._timer = threading.Timer(self._interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.name = "smartdesk-activity-segment-builder"
        self._timer.start()

    def _tick(self) -> None:
        """Process one scheduling cycle."""
        try:
            self._process()
        except Exception:
            self.logger.exception("ActivitySegmentBuilder encountered an error during tick.")
        finally:
            self._schedule()

    def _process(self) -> None:
        """Process one build cycle."""
        db: DbSession = SessionLocal()
        try:
            # Calculate time window: end now, start from one interval ago
            end_time = local_now()
            start_time = end_time - timedelta(seconds=self._interval_seconds)

            # Apply event arrival delay to end time
            safe_end_time = end_time - timedelta(seconds=EVENT_ARRIVAL_DELAY_SECONDS)

            if start_time >= safe_end_time:
                self.logger.warning(
                    f"Invalid time range after applying delay: {start_time.isoformat()} to {safe_end_time.isoformat()}"
                )
                return

            # Initialize repositories with current database session
            os_repo = OSSessionRepository()
            ide_repo = IDESessionRepository()
            browser_repo = BrowserSessionRepository()
            segment_repo = ActivitySegmentRepository()

            self._build_segments_for_timerange(
                db=db,
                user_id=self._user_id,
                device_id=self._device_id,
                start_time_iso=start_time.isoformat(),
                end_time_iso=safe_end_time.isoformat(),
                os_repo=os_repo,
                ide_repo=ide_repo,
                browser_repo=browser_repo,
                segment_repo=segment_repo,
            )
        finally:
            db.close()

    # Helper methods to match the interface used in other services
    def local_now_iso(self) -> str:
        """Get current local time as ISO string."""
        from app.core.time import local_now_iso
        return local_now_iso()

    def parse_iso(self, value: str):
        """Parse ISO string to datetime."""
        from app.core.time import parse_iso
        return parse_iso(value)

    def _get_device_id(self) -> str:
        """Get the current device ID."""
        import socket
        from app.core.config import settings
        if not settings.DEVICE_ID:
            settings.DEVICE_ID = socket.gethostname().lower()
        return settings.DEVICE_ID