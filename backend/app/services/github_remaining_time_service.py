"""Status-aware Remaining Estimate baseline for GitHub lifecycles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math


@dataclass(frozen=True)
class RemainingTimeResult:
    remaining_time_hours: float | None
    remaining_time_status: str
    overrun_hours: float | None = None
    approaching_initial_estimate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class GitHubRemainingTimeService:
    """Compare authoritative active IDE time with the initial estimate."""

    @staticmethod
    def calculate(
        predicted_typical_hours: float | None,
        time_spent: dict,
        lifecycle_status: str = "ACTIVE",
    ) -> RemainingTimeResult:
        if lifecycle_status.upper() == "DONE":
            return RemainingTimeResult(
                remaining_time_hours=0.0,
                remaining_time_status="completed",
            )

        if (
            predicted_typical_hours is None
            or not isinstance(predicted_typical_hours, (int, float))
            or not math.isfinite(predicted_typical_hours)
            or predicted_typical_hours < 0
        ):
            return RemainingTimeResult(None, "initial_prediction_unavailable")

        spent_hours = time_spent.get("time_spent_hours")
        if (
            time_spent.get("time_attribution_status") not in {
                "repository_match", "branch_match"
            }
            or time_spent.get("data_status") != "complete"
            or not isinstance(spent_hours, (int, float))
            or not math.isfinite(spent_hours)
            or spent_hours < 0
        ):
            return RemainingTimeResult(None, "time_spent_unavailable")

        prediction = float(predicted_typical_hours)
        spent = float(spent_hours)
        if spent >= prediction:
            return RemainingTimeResult(
                remaining_time_hours=None,
                remaining_time_status="estimate_exceeded",
                overrun_hours=spent - prediction,
            )

        return RemainingTimeResult(
            remaining_time_hours=prediction - spent,
            remaining_time_status="baseline_available",
            approaching_initial_estimate=prediction > 0 and spent / prediction >= 0.9,
        )
