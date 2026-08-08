"""Focus scoring service.

Calculates focus scores for activity segments based on various signals
like interaction rate, context switching, and engagement metrics.
"""

import math
import statistics
from typing import Any

from app.models.db import ActivitySegmentRecord


class FocusScorer:
    """Service for calculating focus scores from activity signals."""

    def __init__(self) -> None:
        """Initialize the focus scorer."""
        # Weights for different signal components
        self.weights = {
            "active_ratio": 0.3,      # Ratio of time with active input
            "switch_penalty": 0.25,   # Penalty for frequent context switches
            "edit_density": 0.2,      # Density of edits/creations
            "engagement": 0.15,       # Overall engagement with content
            "session_length": 0.1,    # Optimal session length bonus/penalty
        }

    def calculate_focus_score(
        self,
        signals: dict[str, float],
        duration_sec: int,
    ) -> float:
        """Calculate a focus score from 0.0 to 1.0 based on signals.

        Args:
            signals: Dictionary containing signal metrics:
                - active_ratio: Fraction of time with keyboard/mouse activity (0-1)
                - switch_rate: Number of window/app switches per minute (0+)
                - edit_density: Number of edits per minute (0+)
                - engagement: Composite engagement score (0-1)
                - session_length_minutes: Duration in minutes (for optimal length scoring)
            duration_sec: Duration of the segment in seconds

        Returns:
            Focus score between 0.0 (distracted) and 1.0 (highly focused)
        """
        # Extract signals with defaults
        active_ratio = signals.get("active_ratio", 0.0)
        switch_rate = signals.get("switch_rate", 0.0)
        edit_density = signals.get("edit_density", 0.0)
        engagement = signals.get("engagement", 0.0)
        session_length_minutes = duration_sec / 60.0

        # Calculate component scores
        # Active ratio: higher is better (direct mapping)
        active_score = min(active_ratio, 1.0)

        # Switch penalty: exponential decay based on switch rate
        # Optimal switch rate is ~0.5-1 per minute for focused work
        switch_score = math.exp(-min(switch_rate / 2.0, 3.0))  # Penalize high switch rates

        # Edit density: logarithmic scaling to handle wide range
        # More edits generally indicates engagement, but diminishing returns
        if edit_density > 0:
            edit_score = min(math.log(edit_density + 1) / 4.0, 1.0)  # Cap at ~1.0 for 50+ edits/min
        else:
            edit_score = 0.0

        # Engagement: direct mapping (already 0-1 scale)
        engagement_score = engagement

        # Session length: bonus for optimal duration (20-90 minutes), penalty for too short/long
        if 20 <= session_length_minutes <= 90:
            length_score = 1.0
        elif session_length_minutes < 20:
            # Too short: penalize linearly from 0 at 0min to 1 at 20min
            length_score = session_length_minutes / 20.0
        else:
            # Too long: penalize logarithmically for extended sessions
            # Peak at 90 minutes, gradual decline after
            excess_minutes = session_length_minutes - 90
            length_score = max(0.5, 1.0 - (math.log(excess_minutes + 1) / 10.0))

        # Calculate weighted score
        raw_score = (
            self.weights["active_ratio"] * active_score +
            self.weights["switch_penalty"] * switch_score +
            self.weights["edit_density"] * edit_score +
            self.weights["engagement"] * engagement_score +
            self.weights["session_length"] * length_score
        )

        # Ensure score is in [0, 1] range
        return max(0.0, min(1.0, raw_score))

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