"""Family D — monthly rules.

The longest horizon in the catalogue, and the one most exposed to reading noise
as meaning. Every rule here compares two 30-day windows and refuses to speak
unless both are populated: without that guard the first month reports a 100%
improvement on everything, which is arithmetically true and completely empty.
"""

from __future__ import annotations

from datetime import timedelta

from app.services.recommendations.narrative import (
    fmt_minutes,
    fmt_pct,
    magnitude,
)
from app.services.recommendations.registry import rule
from app.services.recommendations.types import (
    Evidence,
    FeatureContext,
    Finding,
    Scope,
    Section,
    Severity,
)

MONTHLY = Scope.MONTHLY
MONTH = timedelta(days=25)


def _delta_finding(
    ctx: FeatureContext,
    label: str,
    dedup: str,
    good_direction: str,
) -> Finding | None:
    """Shared shape for the month-over-month comparisons.

    ``good_direction`` says which way is an improvement, because more
    distraction and more deep work are not the same news.
    """
    change = ctx.num(f"mo_{label}_change")
    if abs(change) < 0.15:
        return None
    up = change > 0
    improving = (up and good_direction == "up") or (not up and good_direction == "down")
    return Finding(
        dedup_key=dedup,
        facts={
            "change": fmt_pct(abs(change)),
            "direction": "up" if up else "down",
            "now_text": fmt_minutes(ctx.num(f"mo_{label}_now")),
            "prev_text": fmt_minutes(ctx.num(f"mo_{label}_prev")),
            "verdict": "an improvement" if improving else "worth watching",
            "magnitude": magnitude(abs(change) * 5),
        },
        evidence=Evidence(
            basis="month_over_month",
            n=int(ctx.num("month_active_days")),
            effect=abs(change) * 5,
            comparison="the preceding 30 days",
            p_value=ctx.get(f"mo_{label}_p"),
        ),
        severity=Severity.LOW if improving else Severity.MEDIUM,
    )


@rule(
    id="MO-01", version=1, scope=MONTHLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"mo_deep_change", "mo_deep_now", "mo_deep_prev", "month_active_days"},
    min_days=45, min_n=10, cooldown=MONTH,
    title="Deep work is {direction} {change} on last month",
    why="A typical day now holds {now_text}, against {prev_text} in the "
        "30 days before — {magnitude} changed, and {verdict}.",
    action="Month-scale movement usually comes from a change in the shape of "
           "the day rather than the hours in it.",
)
def deep_work_month(ctx: FeatureContext) -> Finding | None:
    return _delta_finding(ctx, "deep", "monthly/deep", good_direction="up")


@rule(
    id="MO-02", version=1, scope=MONTHLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"mo_distraction_change", "mo_distraction_now",
              "mo_distraction_prev", "month_active_days"},
    min_days=45, min_n=10, cooldown=MONTH,
    title="Distraction time is {direction} {change}",
    why="A typical day now holds {now_text} of entertainment and social, "
        "against {prev_text} last month — {verdict}.",
    action="The trend matters more than the total; a slow drift is the hard "
           "one to notice from inside it.",
)
def distraction_month(ctx: FeatureContext) -> Finding | None:
    return _delta_finding(ctx, "distraction", "monthly/distraction",
                          good_direction="down")


@rule(
    id="MO-04", version=1, scope=MONTHLY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"best_day_date", "best_day_deep_min", "best_day_weekday",
              "best_day_active_min"},
    min_days=30, cooldown=MONTH,
    title="Your best day this month was {weekday} {date}",
    why="{deep_text} of uninterrupted, high-focus work out of {active_text} "
        "tracked — the highest of any day in the window.",
    action="Worth opening that day on the Timeline and copying its shape "
           "rather than trying to copy its effort.",
)
def best_day_template(ctx: FeatureContext) -> Finding | None:
    if ctx["best_day_deep_min"] < 30:
        return None
    return Finding(
        dedup_key="monthly/best-day",
        facts={
            "weekday": ctx["best_day_weekday"],
            "date": ctx["best_day_date"],
            "deep_text": fmt_minutes(ctx["best_day_deep_min"]),
            "active_text": fmt_minutes(ctx["best_day_active_min"]),
        },
        evidence=Evidence(
            basis="within_month", n=int(ctx.num("month_active_days")),
            comparison="every other day in the window",
        ),
    )


@rule(
    id="MO-06", version=1, scope=MONTHLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"mix_gained", "mix_gained_delta", "mix_lost", "mix_lost_delta"},
    min_days=45, cooldown=MONTH,
    title="Time moved from {lost} to {gained}",
    why="{gained} gained {gained_delta} of your tracked time this month while "
        "{lost} gave up {lost_delta}.",
    action="Category drift is usually the first visible sign that priorities "
           "moved — worth checking it was deliberate.",
)
def category_migration(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="monthly/migration",
        facts={
            "gained": str(ctx["mix_gained"]).replace("_", " "),
            "lost": str(ctx["mix_lost"]).replace("_", " "),
            "gained_delta": fmt_pct(abs(ctx["mix_gained_delta"])),
            "lost_delta": fmt_pct(abs(ctx["mix_lost_delta"])),
        },
        evidence=Evidence(
            basis="month_over_month", n=int(ctx.num("month_active_days")),
            comparison="the preceding 30 days",
            p_value=ctx.get("mix_shift_p"),
        ),
    )


@rule(
    id="MO-07", version=1, scope=MONTHLY, section=Section.INSIGHT,
    severity=Severity.MEDIUM,
    requires={"ide_coverage", "browser_coverage", "month_active_days"},
    min_days=30, cooldown=MONTH,
    title="Tracking covered {ide_pct} of days in the editor, {browser_pct} in the browser",
    why="Every figure in this month's report describes only the days a "
        "collector was actually reporting. Gaps read as quiet days rather "
        "than as missing data.",
    action="{advice}",
)
def coverage(ctx: FeatureContext) -> Finding | None:
    ide, browser = ctx["ide_coverage"], ctx["browser_coverage"]
    # Only raised when coverage is poor enough to distort the month's numbers.
    if ide >= 0.7 and browser >= 0.7:
        return None
    weakest = "IDE" if ide <= browser else "browser"
    return Finding(
        dedup_key="monthly/coverage",
        facts={
            "ide_pct": fmt_pct(min(ide, 1.0)),
            "browser_pct": fmt_pct(min(browser, 1.0)),
            "advice": (
                f"The {weakest} extension is the weaker of the two — worth "
                f"confirming it is installed and enabled before reading this "
                f"month's totals as complete."
            ),
        },
        evidence=Evidence(basis="absolute", n=int(ctx["month_active_days"])),
    )


@rule(
    id="MO-03", version=1, scope=MONTHLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"habit_direction", "habit_weeks", "habit_now", "habit_before"},
    min_days=45, min_n=10, cooldown=MONTH,
    title="A habit has {direction}",
    why="Deep work has held at {now_text} a day for {weeks} consecutive weeks, "
        "against {before_text} in the month before. Three weeks is the point "
        "at which that stops being a good or bad run.",
    action="{advice}",
)
def habit_change(ctx: FeatureContext) -> Finding | None:
    formed = ctx["habit_direction"] == "formed"
    return Finding(
        dedup_key="monthly/habit",
        facts={
            "direction": "formed" if formed else "eroded",
            "now_text": fmt_minutes(ctx["habit_now"]),
            "before_text": fmt_minutes(ctx["habit_before"]),
            "weeks": int(ctx["habit_weeks"]),
            "advice": (
                "Worth identifying what changed so it survives the next busy "
                "month."
                if formed else
                "Habits erode from a change in the shape of the week rather "
                "than a loss of intent -- look at what was added."
            ),
        },
        evidence=Evidence(
            basis="sustained_weeks", n=int(ctx.num("month_active_days")),
            effect=3.0,
            comparison="the days either side of the change point",
            p_value=ctx.get("habit_p"),
        ),
        severity=Severity.LOW if formed else Severity.MEDIUM,
    )


@rule(
    id="MO-05", version=1, scope=MONTHLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"anomaly_day_count", "anomaly_top_day", "anomaly_top_windows"},
    min_days=30, cooldown=MONTH,
    title="{count} day(s) stood out from your normal pattern",
    why="{top_day} had {windows} windows the anomaly detector flagged against "
        "your own history -- clustered enough that something about the day was "
        "genuinely different.",
    action="Outliers are sometimes the best days rather than the worst. Worth "
           "opening that one on the Timeline.",
)
def anomaly_rollup(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="monthly/anomaly-days",
        facts={
            "count": int(ctx["anomaly_day_count"]),
            "top_day": ctx["anomaly_top_day"],
            "windows": int(ctx["anomaly_top_windows"]),
        },
        evidence=Evidence(
            basis="isolation_forest", n=int(ctx["anomaly_day_count"]),
            comparison="the month's ten-minute windows",
        ),
    )
