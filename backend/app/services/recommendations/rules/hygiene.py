"""Family F — hygiene and meta.

These are the rules that tell you the other rules are reading good data. A
silent collector does not raise an error anywhere: it produces a day that looks
quiet, and every rule above will describe that quiet day in perfect good faith.
Worth having first, not last.
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

DAILY = Scope.DAILY
WEEKLY = Scope.WEEKLY
MONTHLY = Scope.MONTHLY
DAY = timedelta(hours=20)
WEEK = timedelta(days=6)
MONTH = timedelta(days=25)


@rule(
    id="HY-01", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.MEDIUM,
    requires={"ide_app_min_today", "ide_sessions_today"}, cooldown=DAY,
    title="The IDE extension does not seem to be reporting",
    why="Your editor was in the foreground for {mins_text} today, but no IDE "
        "sessions were recorded. Edit counts, languages and project time are "
        "missing from everything above.",
    action="Reinstall or re-enable the SmartDesk IDE extension, then restart "
           "the editor.",
)
def ide_layer_silent(ctx: FeatureContext) -> Finding | None:
    minutes = ctx["ide_app_min_today"]
    if minutes < 120 or ctx["ide_sessions_today"] > 0:
        return None
    return Finding(
        dedup_key="hygiene/ide-silent",
        facts={"mins_text": fmt_minutes(minutes)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-03", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"calendar_age_hours"}, cooldown=DAY,
    title="Calendar has not synced in {age_text}",
    why="Meeting-aware suggestions are switched off until it reconnects. "
        "Google expires the refresh token after seven days while the OAuth "
        "app is in Testing status.",
    action="Reconnect from the monitoring dashboard, or publish the OAuth app "
           "to stop the expiry.",
)
def calendar_stale(ctx: FeatureContext) -> Finding | None:
    hours = ctx["calendar_age_hours"]
    if hours < 48:
        return None
    return Finding(
        dedup_key="hygiene/calendar",
        facts={"age_text": f"{int(hours / 24)} days" if hours >= 48 else f"{int(hours)}h"},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-04", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.MEDIUM,
    requires={"pattern_age_hours"}, cooldown=DAY,
    title="Pattern analysis has not run in {age_text}",
    why="Focus levels and anomaly detection on the Insights page are being "
        "served from the last completed run, so they describe older activity "
        "than the rest of the app.",
    action="Run the scheduled task manually, or check that "
           "run_pattern_analysis_daily.cmd is still registered.",
)
def clustering_stale(ctx: FeatureContext) -> Finding | None:
    hours = ctx["pattern_age_hours"]
    if hours < 36:
        return None
    return Finding(
        dedup_key="hygiene/clustering",
        facts={"age_text": f"{int(hours)}h"},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-05", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"window_lag_min"}, cooldown=DAY,
    title="The ten-minute roll-up is behind the timeline",
    why="Activity has been recorded up to {lag_text} past the newest rolled-up "
        "window, so period figures are under-reporting by roughly that much.",
    action="Run refresh_windows_nightly.py to catch up.",
)
def window_table_stale(ctx: FeatureContext) -> Finding | None:
    lag = ctx["window_lag_min"]
    if lag < 180:
        return None
    return Finding(
        dedup_key="hygiene/window-lag",
        facts={"lag_text": fmt_minutes(lag)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-07", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"active_min"}, cooldown=DAY,
    title="Still building your baseline — {days} days recorded",
    why="Comparisons against your own history need about 10 days before the "
        "percentiles mean anything. Until then only directly observable "
        "findings are shown.",
    action="Nothing to do; the personalised suggestions appear on their own.",
)
def insufficient_history(ctx: FeatureContext) -> Finding | None:
    # Deliberately the one rule that fires when the others cannot. Without it
    # a new user sees an empty panel and assumes the feature is broken.
    if ctx.days_of_history >= 10:
        return None
    return Finding(
        dedup_key="hygiene/cold-start",
        facts={"days": ctx.days_of_history},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-02", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.MEDIUM,
    requires={"browser_app_min_today", "browser_sessions_today"}, cooldown=DAY,
    title="The browser extension does not seem to be reporting",
    why="A browser was in the foreground for {mins_text} today with no browser "
        "sessions recorded. Without URLs every host rule goes blind and those "
        "hours fall back to whatever the window title suggests.",
    action="Re-enable the SmartDesk browser extension and reload any open tabs.",
)
def browser_layer_silent(ctx: FeatureContext) -> Finding | None:
    minutes = ctx["browser_app_min_today"]
    if minutes < 120 or ctx["browser_sessions_today"] > 0:
        return None
    return Finding(
        dedup_key="hygiene/browser-silent",
        facts={"mins_text": fmt_minutes(minutes)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-06", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"low_confidence_share"}, cooldown=DAY,
    title="{share} of today was classified with low confidence",
    why="Those segments carry a category the classifier was unsure about, so "
        "they may be filed under the wrong heading in every breakdown.",
    action="Correcting a handful on the Timeline retrains the model — it "
           "already learns from 4,477 stored labels.",
)
def low_confidence(ctx: FeatureContext) -> Finding | None:
    share = ctx["low_confidence_share"]
    if share < 0.15:
        return None
    return Finding(
        dedup_key="hygiene/confidence",
        facts={"share": fmt_pct(share)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-08", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.HIGH,
    requires={"impossible_segments"}, cooldown=DAY,
    title="{count} segments carry impossible timestamps",
    why="Negative durations, end times before start times, or activity dated "
        "in the future. These feed every percentile in the app and would "
        "distort them silently.",
    action="Worth investigating before trusting the comparisons — a clock "
           "change or a timezone bug is the usual cause.",
)
def clock_anomaly(ctx: FeatureContext) -> Finding | None:
    count = ctx["impossible_segments"]
    if count <= 0:
        return None
    return Finding(
        dedup_key="hygiene/clock",
        facts={"count": int(count)},
        evidence=Evidence(basis="absolute", n=int(count)),
    )


@rule(
    id="HY-09", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"labels_unused"}, cooldown=DAY,
    title="{count} corrections are waiting to be trained on",
    why="The classifier is frozen at {accuracy} on held-out human labels "
        "({basis} basis). Corrections made since then are stored but are not "
        "yet influencing anything.",
    action="Run the categoriser's training pass to fold them in.",
)
def model_drift(ctx: FeatureContext) -> Finding | None:
    # Not decay in the coefficients -- the model does not change once trained.
    # The drift is that labelled data keeps arriving and the model keeps not
    # learning from it, so its accuracy figure describes an older world.
    count = ctx["labels_unused"]
    if count < 25:
        return None
    accuracy = ctx.get("model_holdout")
    return Finding(
        dedup_key="hygiene/model-drift",
        facts={
            "count": int(count),
            "accuracy": (
                format(float(accuracy), ".0%") if accuracy is not None
                else "an unknown score"
            ),
            "basis": ctx.get("model_basis") or "unknown",
        },
        evidence=Evidence(basis="absolute", n=int(count)),
    )


# ---------------------------------------------------------------------- #
# Empty periods                                                            #
# ---------------------------------------------------------------------- #
#
# The rules above catch a layer that has gone quiet while the rest of the
# pipeline still runs. These two catch the case where nothing ran at all.
#
# A period with no recorded days is the one situation where silence is the
# wrong answer. The builders return early with baselines only, every rule in
# scope gates out for want of features, and the report comes out clean and
# empty -- indistinguishable from a genuinely quiet week rather than a
# fortnight when the collector was down. These rules make the difference
# visible. Both carry HY- ids on purpose: the report router files anything
# HY- into the caveats footer rather than among the findings, which is where
# a statement about the collector belongs.


@rule(
    id="HY-10", version=1, scope=WEEKLY, section=Section.INSIGHT,
    severity=Severity.HIGH,
    requires={"week_day_count"}, cooldown=WEEK,
    title="No activity was recorded in the week to {week_end}",
    why="The weekly report covers seven days and found none of them. Every "
        "weekly comparison is missing rather than flat, and the figures above "
        "describe an empty period, not a quiet one.",
    action="Check that the SmartDesk collector was running for this week; if "
           "it was stopped, treat this week's report as absent rather than as "
           "a record of low activity.",
)
def week_is_empty(ctx: FeatureContext) -> Finding | None:
    if ctx["week_day_count"] > 0:
        return None
    return Finding(
        dedup_key="hygiene/week-empty",
        facts={"week_end": ctx.get("week_end") or "this week"},
        # Absolute: the claim is "there are no days here", which needs no
        # sample to support it -- it *is* the absence of the sample.
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="HY-11", version=1, scope=MONTHLY, section=Section.INSIGHT,
    severity=Severity.HIGH,
    requires={"month_active_days"}, cooldown=MONTH,
    title="No activity was recorded in the month to {month_end}",
    why="The monthly report covers thirty days and found none of them. The "
        "month-over-month comparisons are absent rather than unchanged, and "
        "no trend, habit or erosion finding could be computed.",
    action="Check that the SmartDesk collector was running for this month; if "
           "it was stopped, treat this month's report as absent rather than "
           "as a record of low activity.",
)
def month_is_empty(ctx: FeatureContext) -> Finding | None:
    if ctx["month_active_days"] > 0:
        return None
    return Finding(
        dedup_key="hygiene/month-empty",
        facts={"month_end": ctx.get("month_end") or "this month"},
        evidence=Evidence(basis="absolute"),
    )
