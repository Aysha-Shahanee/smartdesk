"""Focus scoring service.

Calculates focus scores for activity segments based on various signals
like interaction rate, context switching, and engagement metrics.
"""

import json
import math
from datetime import datetime, timezone
from typing import Any

from app.core.time import parse_iso
from app.models.db import ActivitySegmentRecord


class FocusScorer:
    """Service for calculating focus scores from activity signals."""

    CATEGORY_COEFFICIENTS = {
        "work": 1.0,
        "learn": 0.8,
        "documentation": 0.6,
        "meetings": 0.4,
        "communication": 0.2,
        "system": 0.0,
        "other": 0.0,
        "social_media": -0.5,
        "entertainment": -1.0,
    }

    def __init__(self) -> None:
        """Initialize the focus scorer."""
        self.weights = {
            "active_ratio": 0.3,
            "switch_penalty": 0.25,
            "edit_density": 0.2,
            "engagement": 0.15,
            "session_length": 0.1,
        }

    def calculate_focus_score(
        self,
        signals: dict[str, float],
        duration_sec: int,
        category: str | None = None,
    ) -> float:
        """Calculate a focus score from 0.0 to 1.0 based on signals."""
        active_ratio = min(max(signals.get("active_ratio", 0.0), 0.0), 1.0)
        switch_rate = max(signals.get("switch_rate", 0.0), 0.0)
        edit_density = max(signals.get("edit_density", 0.0), 0.0)
        engagement = min(max(signals.get("engagement", 0.0), 0.0), 1.0)
        session_length_minutes = duration_sec / 60.0

        active_score = active_ratio
        switch_score = math.exp(-min(switch_rate / 2.0, 3.0))

        if edit_density > 0:
            edit_score = min(math.log(edit_density + 1) / 4.0, 1.0)
        else:
            edit_score = 0.0

        engagement_score = engagement

        if 20 <= session_length_minutes <= 90:
            length_score = 1.0
        elif session_length_minutes < 20:
            length_score = session_length_minutes / 20.0
        else:
            excess_minutes = session_length_minutes - 90
            length_score = max(0.5, 1.0 - (math.log(excess_minutes + 1) / 10.0))

        raw_score = (
            self.weights["active_ratio"] * active_score +
            self.weights["switch_penalty"] * switch_score +
            self.weights["edit_density"] * edit_score +
            self.weights["engagement"] * engagement_score +
            self.weights["session_length"] * length_score
        )

        multiplier = self._category_multiplier(category)
        final_score = raw_score * multiplier
        return max(0.0, min(1.0, final_score))

    def _category_multiplier(self, category: str | None) -> float:
        coefficient = self.CATEGORY_COEFFICIENTS.get(category, 0.0)
        return 0.5 + (0.5 * coefficient)

    def score_segment(self, segment: dict[str, Any]) -> tuple[float, str, str]:
        """Score a segment and produce metadata for persistence."""
        duration = max(0.0, float(segment.get("duration", 0.0)))
        category = segment.get("category")
        state = segment.get("state")
        primary_source = segment.get("primary_source")

        signals = self._derive_signals(segment, duration, state, primary_source)
        focus_score = self.calculate_focus_score(signals, int(duration), category)

        concurrent_json = json.dumps(self._build_concurrency_log(segment), ensure_ascii=False)
        signals_json = json.dumps({
            "raw_signals": signals,
            "component_scores": self._component_scores(signals, duration),
            "weights": self.weights,
            "category": category,
            "primary_source": primary_source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False)

        return focus_score, concurrent_json, signals_json

    def _derive_signals(
        self,
        segment: dict[str, Any],
        duration: float,
        state: str | None,
        primary_source: str | None,
    ) -> dict[str, float]:
        duration_min = max(duration / 60.0, 0.01)

        active_ratio = 0.0
        os_sessions = segment.get("sources", {}).get("os", [])
        if os_sessions:
            os_session = os_sessions[0]
            idle_time = getattr(os_session, "idle_time", None)
            if isinstance(idle_time, (int, float)) and duration > 0:
                active_ratio = max(0.0, min(1.0, (duration - min(duration, idle_time)) / duration))
            else:
                active_ratio = 0.8 if state == "active" else 0.2 if state == "idle" else 0.1
        else:
            active_ratio = 0.8 if state == "active" else 0.2 if state == "idle" else 0.1

        edit_count = sum(
            max(int(getattr(ide, "edit_count", 0) or 0), 0)
            for ide in segment.get("sources", {}).get("ide", [])
        )
        edit_density = edit_count / duration_min if duration_min > 0 else 0.0

        file_switches = sum(
            max(int(getattr(ide, "file_switch_count", 0) or 0), 0)
            for ide in segment.get("sources", {}).get("ide", [])
        )
        browser_domains = {
            getattr(browser, "domain", "") or ""
            for browser in segment.get("sources", {}).get("browser", [])
        }
        browser_domains.discard("")
        app_switch_events = len({
            *(getattr(os, "app_name", "") for os in segment.get("sources", {}).get("os", [])),
            *(getattr(ide, "ide_name", "") for ide in segment.get("sources", {}).get("ide", [])),
            *(getattr(browser, "browser_name", "") for browser in segment.get("sources", {}).get("browser", [])),
        }) - 1
        switch_events = file_switches + len(browser_domains) + max(0, app_switch_events)
        switch_rate = switch_events / duration_min if duration_min > 0 else 0.0
        if switch_rate == 0.0:
            switch_rate = 0.5

        engagement = 0.4
        if state == "active":
            engagement = 0.7
        elif state == "idle":
            engagement = 0.25
        elif state == "locked":
            engagement = 0.0
        elif state == "gap":
            engagement = 0.1

        if primary_source == "ide":
            engagement += 0.15
        elif primary_source == "browser":
            engagement += 0.1

        category_bonus = {
            "work": 0.2,
            "learn": 0.15,
            "meetings": 0.1,
            "communication": 0.05,
            "documentation": 0.1,
            "social_media": -0.2,
            "entertainment": -0.3,
        }.get(segment.get("category"), 0.0)
        engagement = min(max(engagement + category_bonus, 0.0), 1.0)

        return {
            "active_ratio": active_ratio,
            "switch_rate": switch_rate,
            "edit_density": edit_density,
            "engagement": engagement,
            "session_length_minutes": duration_min,
        }

    def _build_concurrency_log(self, segment: dict[str, Any]) -> dict[str, Any]:
        active_apps = []
        seen_ids = set()
        browser_domains = set()

        def add_session(session, source_type: str, name: str, extra: dict[str, Any] | None = None):
            session_id = getattr(session, "id", None)
            if session_id in seen_ids:
                return
            seen_ids.add(session_id)
            start = parse_iso(getattr(session, "session_start", ""))
            end = parse_iso(getattr(session, "session_end", "")) if getattr(session, "session_end", None) else datetime.now(timezone.utc)
            if not start or not end:
                return
            overlap_start = max(start, segment["start_time"])
            overlap_end = min(end, segment["end_time"])
            overlap_duration = max(0.0, (overlap_end - overlap_start).total_seconds())
            if overlap_duration <= 0:
                return
            if source_type == "browser":
                browser_domains.add(getattr(session, "domain", "") or "")
            item = {
                "source": source_type,
                "name": name,
                "pid": getattr(session, "process_id", None),
                "overlap_duration_sec": int(overlap_duration),
            }
            if extra:
                item.update(extra)
            active_apps.append(item)

        for os_session in segment.get("sources", {}).get("os", []):
            add_session(os_session, "os", getattr(os_session, "app_name", "os"), {})
        for ide_session in segment.get("sources", {}).get("ide", []):
            name = getattr(ide_session, "ide_name", None) or getattr(ide_session, "active_file_name", None) or "ide"
            add_session(ide_session, "ide", name, {"workspace": getattr(ide_session, "workspace_name", None)})
        for browser_session in segment.get("sources", {}).get("browser", []):
            name = getattr(browser_session, "browser_name", None) or "browser"
            add_session(browser_session, "browser", name, {"domain": getattr(browser_session, "domain", None), "url": getattr(browser_session, "url", None)})

        return {
            "active_applications": active_apps,
            "concurrency_metrics": {
                "max_apps_open": len(active_apps),
                "domain_switches": max(0, len(browser_domains) - 1),
                "source_count": sum(1 for source in ("os", "ide", "browser") if segment.get("sources", {}).get(source)),
            },
        }

    def _component_scores(self, signals: dict[str, float], duration: float) -> dict[str, float]:
        active_score = min(max(signals.get("active_ratio", 0.0), 0.0), 1.0)
        switch_score = math.exp(-min(max(signals.get("switch_rate", 0.0), 0.0) / 2.0, 3.0))
        edit_density = max(signals.get("edit_density", 0.0), 0.0)
        if edit_density > 0:
            edit_score = min(math.log(edit_density + 1) / 4.0, 1.0)
        else:
            edit_score = 0.0
        engagement_score = min(max(signals.get("engagement", 0.0), 0.0), 1.0)
        session_length_minutes = duration / 60.0
        if 20 <= session_length_minutes <= 90:
            length_score = 1.0
        elif session_length_minutes < 20:
            length_score = session_length_minutes / 20.0
        else:
            excess_minutes = session_length_minutes - 90
            length_score = max(0.5, 1.0 - (math.log(excess_minutes + 1) / 10.0))
        return {
            "active_score": active_score,
            "switch_score": switch_score,
            "edit_score": edit_score,
            "engagement_score": engagement_score,
            "length_score": length_score,
        }

    def create_signals_from_segment(
        self,
        segment: ActivitySegmentRecord,
    ) -> dict[str, float]:
        """Extract signal metrics from an activity segment.

        Args:
            segment: Activity segment to analyze

        Returns:
            Dictionary of signal metrics suitable for calculate_focus_score
        """
        signals = {}

        # Extract from signals_json if available
        if segment.signals_json:
            try:
                import json
                signals = json.loads(segment.signals_json)
                # Ensure we have float values
                signals = {k: float(v) for k, v in signals.items() if isinstance(v, (int, float))}
            except (json.JSONDecodeError, TypeError, ValueError):
                signals = {}

        # Calculate derived signals if not provided
        if "active_ratio" not in signals:
            # Default assumption: active if state is 'active', otherwise estimate
            if segment.state == "active":
                signals["active_ratio"] = 0.8  # Assume 80% active time
            elif segment.state == "idle":
                signals["active_ratio"] = 0.2  # Low activity during idle
            elif segment.state == "locked":
                signals["active_ratio"] = 0.0  # No activity when locked
            else:  # gap or unknown
                signals["active_ratio"] = 0.1  # Minimal activity

        if "switch_rate" not in signals:
            # Estimate based on state changes or default low
            signals["switch_rate"] = 0.5  # Default: 0.5 switches per minute

        if "edit_density" not in signals:
            # Estimate based on application type
            editing_apps = ["code", "editor", "ide", "text", "document", "word", "pages"]
            app_lower = (segment.app_name or "").lower()
            title_lower = (segment.title or "").lower()
            detail_lower = (segment.detail or "").lower()

            is_editing_app = any(app in app_lower for app in editing_apps)
            is_editing_context = any(app in title_lower for app in editing_apps) or \
                               any(app in detail_lower for app in editing_apps)

            if is_editing_app or is_editing_context:
                signals["edit_density"] = 5.0  # Moderate editing activity
            else:
                signals["edit_density"] = 0.5  # Low editing activity

        if "engagement" not in signals:
            # Estimate engagement based on state and category
            engagement_map = {
                "active": 0.7,
                "idle": 0.2,
                "locked": 0.0,
                "gap": 0.1,
            }
            base_engagement = engagement_map.get(segment.state, 0.3)

            # Adjust based on category if available
            category_bonus = {
                "work": 0.2,
                "learn": 0.15,
                "meetings": 0.1,
                "communication": 0.05,
            }.get(segment.category, 0.0)

            signals["engagement"] = min(1.0, base_engagement + category_bonus)

        # Ensure session length is present
        if "session_length_minutes" not in signals:
            signals["session_length_minutes"] = max(1.0, segment.duration_sec / 60.0)

        return signals