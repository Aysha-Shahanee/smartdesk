"""Families B and E — daily findings and the planning proposals built on them.

These run once per day against a completed local day, so they can afford to
compare against the full baseline set. Everything here is a comparison against
*your own* distribution: the same numbers on someone else's history would
produce different cards, which is the point.
"""

from __future__ import annotations

from datetime import timedelta

from app.services.recommendations.narrative import (
    fmt_clock,
    fmt_hour_range,
    fmt_minutes,
    fmt_pct,
    magnitude,
)
from app.services.recommendations.baselines import MAD_TO_SIGMA
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
DAY = timedelta(hours=20)

#: Feature carrying the user's sensitivity preference, when they have set one.
#: Absent means 1.0, which is the shipped behaviour.
SENSITIVITY_KEY = "pref.sensitivity"


def _bar(ctx: FeatureContext) -> float:
    """The deviation bar, after the user's sensitivity preference.

    Read from the context rather than the database because rules are pure —
    a rule that opened a session would be untestable and would put a query on
    the hot path of every tick.
    """
    return ORDINARY_SPREAD * ctx.num(SENSITIVITY_KEY, 1.0)


#: The bar these rules have always used — one median absolute deviation above
#: the median — restated in the scaled units the baselines now report.
#:
#: 1 MAD is 0.6745 sigma, so the trigger point is numerically exactly where it
#: was. Only the z-scores the cards quote have changed, and only because they
#: are now real z-scores rather than raw MAD counts. Moving the bar as well
#: would have buried a calibration fix inside a silent change to how often
#: every one of these rules fires.
ORDINARY_SPREAD = 1.0 / MAD_TO_SIGMA


def _stat_evidence(ctx: FeatureContext, metric: str, value: float) -> Evidence:
    """Evidence comparing a measurement against its own baseline."""
    median = ctx.num(f"baseline.{metric}.p50")
    sigma = ctx.num(f"baseline.{metric}.sigma")
    z = (value - median) / sigma if sigma > 0 else 0.0
    return Evidence(
        basis=f"personal_{metric}",
        n=int(ctx.num(f"baseline.{metric}.n")),
        effect=z,
        comparison=f"your 30-day {metric.replace('_', ' ')}",
    )


# --------------------------------------------------------------------- #
# B — what happened today                                                 #
# --------------------------------------------------------------------- #

@rule(
    id="DY-01", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"best_hour", "best_hour_focus", "scored_hour_count"},
    min_days=5, cooldown=DAY,
    title="Your strongest hour was {hour_range}",
    why="Focus averaged {score} across that hour — the best of {hours} hours "
        "with enough activity to score.",
    action="Protect this hour tomorrow. It is the cheapest improvement "
           "available because it costs no extra time.",
)
def best_hour(ctx: FeatureContext) -> Finding | None:
    if ctx["scored_hour_count"] < 3:
        return None
    return Finding(
        dedup_key="insight/best-hour",
        facts={
            "hour_range": fmt_hour_range(ctx["best_hour"]),
            "score": f"{ctx['best_hour_focus']:.2f}",
            "hours": int(ctx["scored_hour_count"]),
        },
        evidence=Evidence(
            basis="within_day", n=int(ctx["scored_hour_count"]),
            comparison="the other scored hours today",
        ),
    )


@rule(
    id="DY-02", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"worst_hour", "worst_hour_focus", "scored_hour_count"},
    min_days=5, cooldown=DAY,
    title="{hour_range} was the weakest stretch",
    why="Focus averaged {score} there, against {best_score} in your best hour "
        "the same day.",
    action="Put low-concentration work here — email, admin, review — rather "
           "than fighting it.",
)
def worst_hour(ctx: FeatureContext) -> Finding | None:
    if ctx["scored_hour_count"] < 3:
        return None
    worst, best = ctx["worst_hour_focus"], ctx.num("best_hour_focus")
    # Only worth saying when the two ends of the day actually differ.
    if best <= 0 or worst / best > 0.7:
        return None
    return Finding(
        dedup_key="insight/worst-hour",
        facts={
            "hour_range": fmt_hour_range(ctx["worst_hour"]),
            "score": f"{worst:.2f}",
            "best_score": f"{best:.2f}",
        },
        evidence=Evidence(
            basis="within_day", n=int(ctx["scored_hour_count"]),
            comparison="the other scored hours today",
        ),
    )


@rule(
    id="DY-03", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"deep_work_min", "baseline.deep_work_min.p50",
              "baseline.deep_work_min.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="Deep work was {direction} today: {actual_text}",
    why="Your usual day holds {median_text} of uninterrupted, high-focus work. "
        "Today came in {magnitude} {direction}.",
    action="{advice}",
)
def deep_work_vs_baseline(ctx: FeatureContext) -> Finding | None:
    actual = ctx["deep_work_min"]
    median = ctx["baseline.deep_work_min.p50"]
    sigma = ctx.num("baseline.deep_work_min.sigma")
    if sigma <= 0:
        return None
    z = (actual - median) / sigma
    # Inside the ordinary spread is an ordinary day, and saying so every day
    # would train the user to ignore the panel.
    if abs(z) < _bar(ctx):
        return None
    up = z > 0
    return Finding(
        dedup_key="insight/deep-work",
        facts={
            "actual_text": fmt_minutes(actual),
            "median_text": fmt_minutes(median),
            "direction": "up" if up else "down",
            "magnitude": magnitude(z),
            "advice": (
                "Worth noting what made today work — same hours, same "
                "environment, fewer interruptions."
                if up else
                "Look at what fragmented the day; the total time was probably "
                "there, just cut into smaller pieces."
            ),
        },
        evidence=_stat_evidence(ctx, "deep_work_min", actual),
        severity=Severity.LOW if up else Severity.MEDIUM,
    )


@rule(
    id="DY-04", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"frag_index", "baseline.frag_index.p50", "baseline.frag_index.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="The day was cut into {count} pieces",
    why="That is {rate} separate activities per active hour, against your "
        "usual {median}. The time was there; it arrived in fragments.",
    action="Pick one block tomorrow — even forty minutes — and close "
           "everything not needed for it.",
)
def fragmentation(ctx: FeatureContext) -> Finding | None:
    index = ctx["frag_index"]
    median = ctx["baseline.frag_index.p50"]
    sigma = ctx.num("baseline.frag_index.sigma")
    if sigma <= 0 or index <= median + _bar(ctx) * sigma:
        return None
    return Finding(
        dedup_key="insight/fragmentation",
        facts={
            "count": int(ctx.num("segment_count")),
            "rate": f"{index:.0f}",
            "median": f"{median:.0f}",
        },
        evidence=_stat_evidence(ctx, "frag_index", index),
    )


@rule(
    id="DY-05", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"longest_block_min", "longest_block_start"},
    min_days=3, cooldown=DAY,
    title="Longest unbroken block: {block_text}",
    why="It started at {start} and ran without a real interruption.",
    action="This is the shape worth repeating — one block, one thing.",
)
def longest_block(ctx: FeatureContext) -> Finding | None:
    minutes = ctx["longest_block_min"]
    if minutes < 30:
        return None
    return Finding(
        dedup_key="insight/longest-block",
        facts={
            "block_text": fmt_minutes(minutes),
            "start": ctx["longest_block_start"],
        },
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="DY-06", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"distraction_share", "distraction_min",
              "baseline.distraction_share.p50", "baseline.distraction_share.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="Distractions took {share} of the day",
    why="{mins_text} on entertainment and social, against a usual {median}. "
        "That is {magnitude} above your own norm rather than above anyone's "
        "standard.",
    action="The pattern matters more than the total — check when it happened "
           "and what preceded it.",
)
def distraction_share(ctx: FeatureContext) -> Finding | None:
    share = ctx["distraction_share"]
    median = ctx["baseline.distraction_share.p50"]
    sigma = ctx.num("baseline.distraction_share.sigma")
    if sigma <= 0 or share <= median + _bar(ctx) * sigma:
        return None
    return Finding(
        dedup_key="insight/distraction",
        facts={
            "share": fmt_pct(share),
            "mins_text": fmt_minutes(ctx["distraction_min"]),
            "median": fmt_pct(median),
            "magnitude": magnitude((share - median) / sigma),
        },
        evidence=_stat_evidence(ctx, "distraction_share", share),
    )


@rule(
    id="DY-08", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"day_start_hour", "baseline.start_hour.p50", "baseline.start_hour.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="You started {delta_text} {direction} than usual",
    why="First activity at {actual}, against a typical {median}.",
    action="{advice}",
)
def start_drift(ctx: FeatureContext) -> Finding | None:
    actual = ctx["day_start_hour"]
    median = ctx["baseline.start_hour.p50"]
    delta_hours = actual - median
    if abs(delta_hours) < 1.5:
        return None
    later = delta_hours > 0
    return Finding(
        dedup_key="insight/start-drift",
        facts={
            "delta_text": fmt_minutes(abs(delta_hours) * 60),
            "direction": "later" if later else "earlier",
            "actual": fmt_clock(actual),
            "median": fmt_clock(median),
            "advice": (
                "A late start compresses the day rather than shortening it — "
                "the work still happens, just under more pressure."
                if later else
                "Early starts are among your better days; worth seeing if it "
                "holds."
            ),
        },
        evidence=_stat_evidence(ctx, "start_hour", actual),
    )


@rule(
    id="DY-09", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"day_stop_hour", "baseline.stop_hour.p90", "baseline.stop_hour.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="You worked later than on 90% of your days",
    why="Last activity at {actual}, where your 90th percentile is {p90}.",
    action="One late night is fine. Three in a week is a schedule problem "
           "rather than a workload one.",
)
def stop_drift(ctx: FeatureContext) -> Finding | None:
    actual = ctx["day_stop_hour"]
    p90 = ctx["baseline.stop_hour.p90"]
    if actual <= p90:
        return None
    return Finding(
        dedup_key="insight/stop-drift",
        facts={"actual": fmt_clock(actual), "p90": fmt_clock(p90)},
        evidence=_stat_evidence(ctx, "stop_hour", actual),
    )


@rule(
    id="DY-12", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"switch_total", "active_min"}, min_days=5, cooldown=DAY,
    title="{switches} app switches across {active_text}",
    why="That is roughly one every {per_switch}. Even a short re-orientation "
        "after each adds up to a meaningful share of the day.",
    action="Batching similar work is the only reliable fix; willpower is not.",
)
def switching_cost(ctx: FeatureContext) -> Finding | None:
    switches = ctx["switch_total"]
    active = ctx["active_min"]
    if switches < 40 or active <= 0:
        return None
    return Finding(
        dedup_key="insight/switching",
        facts={
            "switches": int(switches),
            "active_text": fmt_minutes(active),
            "per_switch": fmt_minutes(active / switches),
        },
        evidence=Evidence(basis="absolute", n=int(switches)),
    )


@rule(
    id="DY-13", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"anomaly_count", "anomaly_worst_at"}, min_days=7, cooldown=DAY,
    title="{count} stretches did not look like your normal day",
    why="The clustering flagged them as outliers against your own history; "
        "the most unusual began at {at}.",
    action="Worth a glance at the timeline around then — outliers are "
           "sometimes the best hours rather than the worst.",
)
def anomalies(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="insight/anomalies",
        facts={"count": int(ctx["anomaly_count"]), "at": ctx["anomaly_worst_at"]},
        evidence=Evidence(
            basis="isolation_forest", n=int(ctx["anomaly_count"]),
            comparison="the day's ten-minute windows",
        ),
    )


@rule(
    id="DY-14", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"top_category", "top_category_min", "top_category_share"},
    min_days=3, cooldown=DAY,
    title="{category} took {share} of the day",
    why="{mins_text} of {active_text} tracked.",
    action="Check that matches what you intended today to be about.",
)
def where_time_went(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="insight/top-category",
        facts={
            "category": str(ctx["top_category"]).replace("_", " ").capitalize(),
            "share": fmt_pct(ctx["top_category_share"]),
            "mins_text": fmt_minutes(ctx["top_category_min"]),
            "active_text": fmt_minutes(ctx.num("active_min")),
        },
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="DY-15", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"uncategorised_share", "active_min"}, min_days=1, cooldown=DAY,
    title="{share} of today could not be categorised",
    why="Those {mins_text} are excluded from every category figure above, so "
        "the percentages describe a slightly shorter day than you had.",
    action="Correcting a few of them on the Timeline both fixes today and "
           "trains the classifier.",
)
def uncategorised(ctx: FeatureContext) -> Finding | None:
    share = ctx["uncategorised_share"]
    if share < 0.05:
        return None
    return Finding(
        dedup_key="data/uncategorised",
        facts={
            "share": fmt_pct(share),
            "mins_text": fmt_minutes(share * ctx["active_min"]),
        },
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="DY-07", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"idle_share", "idle_min", "baseline.idle_share.p50",
              "baseline.idle_share.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="{share} of the tracked day was idle",
    why="{mins_text} with the machine on and unattended, against a usual "
        "{median}. Idle time is excluded from every active total above.",
    action="Mostly worth knowing so the active figures are read correctly.",
)
def idle_share(ctx: FeatureContext) -> Finding | None:
    share = ctx["idle_share"]
    median = ctx["baseline.idle_share.p50"]
    sigma = ctx.num("baseline.idle_share.sigma")
    if sigma <= 0 or share <= median + _bar(ctx) * sigma:
        return None
    return Finding(
        dedup_key="insight/idle",
        facts={
            "share": fmt_pct(share),
            "mins_text": fmt_minutes(ctx["idle_min"]),
            "median": fmt_pct(median),
        },
        evidence=_stat_evidence(ctx, "idle_share", share),
    )


@rule(
    id="DY-10", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.MEDIUM,
    requires={"post_meeting_focus", "control_focus", "post_meeting_relative",
              "post_meeting_n"},
    min_days=21, min_n=8, cooldown=DAY,
    title="Focus after meetings runs {change} {direction}",
    why="{treated} in the hour after a meeting against {control} in the same "
        "hour on meeting-free days, matched by weekday and hour across "
        "{n} windows in each arm.",
    action="{advice}",
)
def post_meeting_recovery(ctx: FeatureContext) -> Finding | None:
    # This is the rule the hardcoded page claimed without measuring. The
    # estimate is a median of matched pairs, both arms cleared the sample
    # floor in effects.py, and the wording says "matched" rather than
    # "caused" — all three are the difference from what it replaces.
    relative = ctx["post_meeting_relative"]
    if abs(relative) < 0.10:
        return None
    down = relative < 0
    return Finding(
        dedup_key="insight/post-meeting",
        facts={
            "change": fmt_pct(abs(relative)),
            "direction": "lower" if down else "higher",
            "treated": f"{ctx['post_meeting_focus']:.2f}",
            "control": f"{ctx['control_focus']:.2f}",
            "n": int(ctx["post_meeting_n"]),
            "advice": (
                "Leaving ten minutes after a meeting before starting deep work "
                "costs less than the recovery does."
                if down else
                "Meetings do not appear to cost you the hour after them."
            ),
        },
        evidence=Evidence(
            basis="matched_pairs", n=int(ctx["post_meeting_n"]),
            effect=abs(relative) * 5,
            comparison="the same hour-of-week on meeting-free days",
            p_value=ctx.get("post_meeting_p"),
        ),
        severity=Severity.MEDIUM if down else Severity.LOW,
    )


@rule(
    id="DY-11", version=1, scope=DAILY, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"mix_distance", "mix_up", "mix_down", "mix_up_delta",
              "mix_down_delta"},
    min_days=10, cooldown=DAY,
    title="Today looked different from your usual mix",
    why="{up} took {up_delta} more of the day than normal and {down} took "
        "{down_delta} less.",
    action="An unusual day is not a bad one — worth checking it matched what "
           "the day was for.",
)
def mix_divergence(ctx: FeatureContext) -> Finding | None:
    # L1 distance over category shares, bounded in [0, 2]. A third of the day
    # rearranged is the point at which the shape genuinely differs rather than
    # simply not being identical.
    if ctx["mix_distance"] < 0.35:
        return None
    return Finding(
        dedup_key="insight/mix",
        facts={
            "up": str(ctx["mix_up"]).replace("_", " "),
            "down": str(ctx["mix_down"]).replace("_", " "),
            "up_delta": fmt_pct(abs(ctx["mix_up_delta"])),
            "down_delta": fmt_pct(abs(ctx["mix_down_delta"])),
        },
        evidence=Evidence(
            basis="personal_mix", n=int(ctx.num("baseline.focus.n")),
            effect=ctx["mix_distance"] * 3,
            comparison="your 30-day category split",
        ),
    )


@rule(
    id="DY-16", version=1, scope=DAILY, section=Section.BEHAVIOUR,
    severity=Severity.LOW,
    requires={"deep_work_min"}, min_days=1, cooldown=DAY,
    title="{verdict}: {actual_text} against a {target_text} target",
    why="{gap_text}",
    action="{advice}",
)
def target_adherence(ctx: FeatureContext) -> Finding | None:
    # Silent unless someone set a target. A goal nobody chose is not a finding,
    # and defaulting one would make every day a failure by construction.
    from app.core.config import settings

    target = float(settings.DAILY_DEEP_WORK_TARGET_MIN or 0)
    if target <= 0:
        return None

    actual = ctx["deep_work_min"]
    met = actual >= target
    return Finding(
        dedup_key="insight/target",
        facts={
            "verdict": "Target met" if met else "Short of target",
            "actual_text": fmt_minutes(actual),
            "target_text": fmt_minutes(target),
            "gap_text": (
                "You cleared it by " + fmt_minutes(actual - target) + "."
                if met else
                fmt_minutes(target - actual) + " short."
            ),
            "advice": (
                "Worth noting what the day did differently."
                if met else
                "One protected block tomorrow usually closes a gap this size."
            ),
        },
        evidence=Evidence(basis="absolute"),
        severity=Severity.LOW if met else Severity.MEDIUM,
    )
