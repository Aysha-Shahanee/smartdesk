"""Family C — weekly rules.

Run on Mondays over the seven completed days behind them. Everything here needs
several weeks of history to say anything, so the ``min_days`` gates are the
strictest in the catalogue — a trend fitted through two points is not a trend.
"""

from __future__ import annotations

from datetime import timedelta

from app.services.recommendations.narrative import fmt_minutes, fmt_pct
from app.services.recommendations.registry import rule
from app.services.recommendations.types import (
    Evidence,
    FeatureContext,
    Finding,
    Scope,
    Section,
    Severity,
)

WEEKLY = Scope.WEEKLY
WEEK = timedelta(days=6)


@rule(
    id="WK-01", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"best_weekday", "best_weekday_deep", "worst_weekday",
              "worst_weekday_deep", "weekday_sample_weeks"},
    min_days=14, cooldown=WEEK,
    title="{best} is consistently your strongest day",
    why="{best} averages {best_text} of deep work against {worst_text} on "
        "{worst}, across every recorded week.",
    action="Put the work that most needs concentration on {best}, and the "
           "meetings and admin on {worst}.",
)
def strongest_weekday(ctx: FeatureContext) -> Finding | None:
    best, worst = ctx["best_weekday_deep"], ctx["worst_weekday_deep"]
    # A gap smaller than half an hour is not worth reorganising a week around.
    if best - worst < 30:
        return None
    return Finding(
        dedup_key="weekly/weekday-shape",
        facts={
            "best": ctx["best_weekday"],
            "worst": ctx["worst_weekday"],
            "best_text": fmt_minutes(best),
            "worst_text": fmt_minutes(worst),
        },
        evidence=Evidence(
            basis="personal_weekday", n=int(ctx["weekday_sample_weeks"]),
            effect=(best - worst) / 60.0,
            comparison="the same weekday across recorded weeks",
        ),
    )


@rule(
    id="WK-02", version=1, scope=WEEKLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"weekend_share", "weekend_min"}, min_days=10, cooldown=WEEK,
    title="{share} of the week's work happened at the weekend",
    why="{mins_text} across Saturday and Sunday.",
    action="Worth checking that was a choice rather than weekday work "
           "spilling over.",
)
def weekend_split(ctx: FeatureContext) -> Finding | None:
    share = ctx["weekend_share"]
    if share < 0.2:
        return None
    return Finding(
        dedup_key="weekly/weekend",
        facts={"share": fmt_pct(share), "mins_text": fmt_minutes(ctx["weekend_min"])},
        evidence=Evidence(basis="absolute"),
        severity=Severity.MEDIUM if share > 0.4 else Severity.LOW,
    )


@rule(
    id="WK-03", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"deep_trend_slope", "deep_trend_weeks", "deep_trend_first",
              "deep_trend_last"},
    min_days=28, cooldown=WEEK,
    title="Deep work is trending {direction}",
    why="{first_text} a week four weeks ago against {last_text} now — a median "
        "change of {slope_text} per week.",
    action="{advice}",
)
def four_week_trend(ctx: FeatureContext) -> Finding | None:
    slope = ctx["deep_trend_slope"]
    # Under fifteen minutes a week is inside the noise of how blocks get
    # stitched together, and calling it a trend would be over-reading.
    if abs(slope) < 15:
        return None
    up = slope > 0
    return Finding(
        dedup_key="weekly/trend",
        facts={
            "direction": "up" if up else "down",
            "first_text": fmt_minutes(ctx["deep_trend_first"]),
            "last_text": fmt_minutes(ctx["deep_trend_last"]),
            "slope_text": fmt_minutes(abs(slope)),
            "advice": (
                "Whatever changed four weeks ago is working. Worth knowing what "
                "it was before it drifts back."
                if up else
                "Look at what has been added to the weeks since — the total "
                "hours may be unchanged while the uninterrupted ones are not."
            ),
        },
        evidence=Evidence(
            basis="theil_sen", n=int(ctx["deep_trend_weeks"]), effect=slope / 60.0,
            comparison="weekly deep-work totals",
        ),
        severity=Severity.LOW if up else Severity.MEDIUM,
    )


@rule(
    id="WK-04", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"meeting_focus_rho", "meeting_focus_n"},
    min_days=21, min_n=10, cooldown=WEEK,
    title="Meeting-heavy days score {direction} on focus",
    why="Rank correlation of {rho} between daily meeting minutes and daily "
        "focus, across {n} recorded days. That is an association, not a cause.",
    action="{advice}",
)
def meeting_load_vs_focus(ctx: FeatureContext) -> Finding | None:
    rho = ctx["meeting_focus_rho"]
    # Below 0.3 the relationship is too weak to mention without overstating it,
    # which is exactly what the hardcoded "40% drop after meetings" did.
    if abs(rho) < 0.3:
        return None
    negative = rho < 0
    return Finding(
        dedup_key="weekly/meeting-load",
        facts={
            "direction": "lower" if negative else "higher",
            "rho": f"{rho:+.2f}",
            "n": int(ctx["meeting_focus_n"]),
            "advice": (
                "Try batching meetings into one part of the day and see whether "
                "the correlation weakens next month."
                if negative else
                "Meetings do not appear to be costing you focus — no change needed."
            ),
        },
        evidence=Evidence(
            basis="spearman", n=int(ctx["meeting_focus_n"]), effect=abs(rho) * 3,
            comparison="daily meeting minutes against daily focus",
        ),
        severity=Severity.MEDIUM if negative else Severity.LOW,
    )


@rule(
    id="WK-05", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"week_active_iqr", "week_active_median", "week_day_count"},
    min_days=14, cooldown=WEEK,
    title="The week was uneven",
    why="Daily active time spread across {iqr_text} between your quieter and "
        "busier days, around a median of {median_text}.",
    action="Evening out the load usually costs nothing and makes the heavy "
           "days survivable.",
)
def consistency(ctx: FeatureContext) -> Finding | None:
    iqr, median = ctx["week_active_iqr"], ctx["week_active_median"]
    # Only call it uneven when the spread exceeds the middle of the week.
    if median <= 0 or iqr < median:
        return None
    return Finding(
        dedup_key="weekly/consistency",
        facts={"iqr_text": fmt_minutes(iqr), "median_text": fmt_minutes(median)},
        evidence=Evidence(
            basis="within_week", n=int(ctx["week_day_count"]),
            effect=iqr / max(median, 1.0),
            comparison="this week's daily totals",
        ),
    )


@rule(
    id="WK-07", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"recurring_hour", "recurring_weeks"}, min_days=21, min_n=3,
    cooldown=WEEK,
    title="{slot} is reliably a weak slot",
    why="It has clustered as distracted in {weeks} of the last four weeks. A "
        "pattern that regular is a habit rather than a run of bad afternoons.",
    action="Either schedule something undemanding there on purpose, or change "
           "what happens just before it.",
)
def recurring_distraction(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="weekly/recurring-slot",
        facts={
            "slot": ctx["recurring_hour"],
            "weeks": int(ctx["recurring_weeks"]),
        },
        evidence=Evidence(
            basis="kmeans_focus_level", n=int(ctx["recurring_weeks"]),
            comparison="the same hour of the week across four weeks",
        ),
    )


@rule(
    id="WK-08", version=1, scope=WEEKLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"top_workspace", "top_workspace_min"}, min_days=7, cooldown=WEEK,
    title="Most editor time went to {workspace}",
    why="{mins_text} in the IDE this week across {count} project(s).",
    action="Check that matches where you meant the week to go.",
)
def project_allocation(ctx: FeatureContext) -> Finding | None:
    if ctx["top_workspace_min"] < 30:
        return None
    return Finding(
        dedup_key="weekly/projects",
        facts={
            "workspace": ctx["top_workspace"],
            "mins_text": fmt_minutes(ctx["top_workspace_min"]),
            "count": int(ctx.num("workspace_count", 1)),
        },
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="WK-10", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"week_learn_share", "prior_learn_share", "week_learn_min"},
    min_days=21, cooldown=WEEK,
    title="Learning time is {direction}",
    why="{share} of this week went to learning, against {prior} across the "
        "weeks before it — {mins_text} in total.",
    action="{advice}",
)
def learning_balance(ctx: FeatureContext) -> Finding | None:
    now, prior = ctx["week_learn_share"], ctx["prior_learn_share"]
    if prior <= 0 or abs(now - prior) < 0.05:
        return None
    down = now < prior
    return Finding(
        dedup_key="weekly/learning",
        facts={
            "direction": "down" if down else "up",
            "share": fmt_pct(now),
            "prior": fmt_pct(prior),
            "mins_text": fmt_minutes(ctx["week_learn_min"]),
            "advice": (
                "Learning is the first thing a busy week drops and the last "
                "thing it misses. Worth booking rather than hoping for."
                if down else
                "Worth keeping — this is usually the first thing a busy week "
                "loses."
            ),
        },
        evidence=Evidence(
            basis="personal_prior_weeks", n=int(ctx.num("week_day_count")),
            effect=abs(now - prior) * 10,
            comparison="the preceding three weeks",
        ),
    )


@rule(
    id="WK-11", version=1, scope=WEEKLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"deep_streak_days", "deep_streak_bar"}, min_days=14, cooldown=WEEK,
    title="{days}-day deep-work streak",
    why="Every one of the last {days} days cleared your own median of "
        "{bar_text} of uninterrupted work.",
    action="Streaks are worth protecting mainly because restarting one is "
           "harder than continuing it.",
)
def deep_streak(ctx: FeatureContext) -> Finding | None:
    days = ctx["deep_streak_days"]
    if days < 3:
        return None
    return Finding(
        dedup_key="weekly/streak",
        facts={"days": int(days), "bar_text": fmt_minutes(ctx["deep_streak_bar"])},
        evidence=Evidence(
            basis="personal_median", n=int(days),
            comparison="your 30-day deep-work median",
        ),
    )


@rule(
    id="WK-12", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"late_night_count", "week_day_count"}, min_days=14, cooldown=WEEK,
    title="{count} sessions ran past midnight this week",
    why="One late night is a deadline. {count} in a week is the schedule "
        "rather than the workload.",
    action="Pick the two days that most need protecting and set a hard stop on "
           "those first.",
)
def late_nights(ctx: FeatureContext) -> Finding | None:
    count = ctx["late_night_count"]
    if count < 2:
        return None
    return Finding(
        dedup_key="weekly/late-nights",
        facts={"count": int(count)},
        evidence=Evidence(
            basis="absolute", n=int(ctx["week_day_count"]),
            effect=count,
        ),
        severity=Severity.HIGH if count >= 4 else Severity.MEDIUM,
    )


@rule(
    id="WK-06", version=1, scope=WEEKLY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"week_focus_slope", "week_focus_first", "week_focus_last",
              "week_focus_days"},
    min_days=14, cooldown=WEEK,
    title="Focus {direction} across the week",
    why="{first} on the first active day against {last} on the last, across "
        "{days} days.",
    action="{advice}",
)
def within_week_decay(ctx: FeatureContext) -> Finding | None:
    slope = ctx["week_focus_slope"]
    # Focus is a 0-1 score, so the slope is per-day drift in that unit. Below
    # 0.02 a day the week is flat within measurement noise.
    if abs(slope) < 0.02:
        return None
    down = slope < 0
    return Finding(
        dedup_key="weekly/decay",
        facts={
            "direction": "fell" if down else "climbed",
            "first": format(ctx["week_focus_first"], ".2f"),
            "last": format(ctx["week_focus_last"], ".2f"),
            "days": int(ctx["week_focus_days"]),
            "advice": (
                "A week that fades usually front-loads its hardest work. "
                "Moving one demanding task later can even it out."
                if down else
                "Worth knowing your week builds rather than fades -- the "
                "hardest work does not have to go on Monday."
            ),
        },
        evidence=Evidence(
            basis="theil_sen", n=int(ctx["week_focus_days"]),
            effect=abs(slope) * 20,
            comparison="this week's daily focus scores",
        ),
        severity=Severity.MEDIUM if down else Severity.LOW,
    )


@rule(
    id="WK-09", version=1, scope=WEEKLY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"top_language", "top_language_share", "top_language_min",
              "language_count"},
    min_days=7, cooldown=WEEK,
    title="{language} took {share} of editor time",
    why="{mins_text} across {count} language(s) this week.",
    action="Mostly context for the project split above.",
)
def language_mix(ctx: FeatureContext) -> Finding | None:
    if ctx["top_language_min"] < 30:
        return None
    return Finding(
        dedup_key="weekly/languages",
        facts={
            "language": str(ctx["top_language"]).capitalize(),
            "share": fmt_pct(ctx["top_language_share"]),
            "mins_text": fmt_minutes(ctx["top_language_min"]),
            "count": int(ctx["language_count"]),
        },
        evidence=Evidence(basis="absolute"),
    )
