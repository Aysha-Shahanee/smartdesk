"""Family E — planning proposals.

Split out of ``daily.py`` once there were eight of them. These differ from the
behaviour family in what they ask for: a behaviour finding reports what
happened, a planning proposal asks for a change to the shape of the next day or
week. They run on the daily tick because that is when the evidence is freshest,
not because they describe a day.
"""

from __future__ import annotations

from datetime import timedelta

from app.services.recommendations.narrative import (
    fmt_clock,
    fmt_hour_range,
    fmt_minutes,
    fmt_pct,
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

DAILY = Scope.DAILY
DAY = timedelta(hours=20)


@rule(
    id="PL-01", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.MEDIUM,
    requires={"peak_hour_top", "baseline.run_len.p75", "baseline.focus.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="Book your hard work into {peak_range}",
    why="It is consistently your strongest hour across the last 30 days, and "
        "your sustainable run length is about {run_text}.",
    action="Hold {peak_range} for the one task that needs the most thought, "
           "and let the calendar fill around it.",
)
def deep_work_block(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="planning/deep-block",
        facts={
            "peak_range": fmt_hour_range(ctx["peak_hour_top"]),
            "run_text": fmt_minutes(ctx["baseline.run_len.p75"]),
        },
        evidence=Evidence(
            basis="personal_hour_median", n=int(ctx["baseline.focus.n"]),
            comparison="hour-of-day focus across 30 days",
        ),
    )


@rule(
    id="PL-02", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"trough_hour_top", "baseline.focus.n"}, min_days=10, min_n=8,
    cooldown=DAY,
    title="Put meetings and admin in {trough_range}",
    why="That hour scores lowest for you across the last 30 days, so it costs "
        "least to spend on work that does not need deep concentration.",
    action="Move recurring meetings here and keep your strong hours clear.",
)
def meeting_batch_window(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="planning/meeting-batch",
        facts={"trough_range": fmt_hour_range(ctx["trough_hour_top"])},
        evidence=Evidence(
            basis="personal_hour_median", n=int(ctx["baseline.focus.n"]),
            comparison="hour-of-day focus across 30 days",
        ),
    )


@rule(
    id="PL-03", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.MEDIUM,
    requires={"peak_clash_count", "peak_clash_title", "peak_clash_hour"},
    min_days=10, cooldown=DAY,
    title="{count} meeting(s) sit inside your best hours",
    why="'{title}' is booked at {clash_hour}, which is one of the two hours "
        "you consistently score highest in.",
    action="Moving it costs nothing and buys back the hour you are most able "
           "to use.",
)
def peak_hour_conflict(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="planning/peak-clash",
        facts={
            "count": int(ctx["peak_clash_count"]),
            "title": ctx["peak_clash_title"],
            "clash_hour": fmt_hour_range(ctx["peak_clash_hour"]),
        },
        evidence=Evidence(
            basis="personal_hour_median", n=int(ctx.num("baseline.focus.n")),
            comparison="hour-of-day focus across 30 days",
        ),
    )


@rule(
    id="PL-04", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.MEDIUM,
    requires={"post_meeting_relative", "post_meeting_n", "baseline.run_len.p50"},
    min_days=21, min_n=8, cooldown=DAY,
    title="Leave a {buffer_text} buffer after meetings",
    why="Your focus in the hour after a meeting runs {change} below matched "
        "meeting-free hours, measured across {n} windows in each arm.",
    action="Book the buffer rather than intending it — the next thing on the "
           "calendar will take it otherwise.",
)
def post_meeting_buffer(ctx: FeatureContext) -> Finding | None:
    # Sized from the measured effect rather than a guessed 30 minutes: a small
    # measured cost earns a small buffer, and a large one earns a large buffer.
    relative = ctx["post_meeting_relative"]
    if relative >= -0.10:
        return None
    buffer_min = max(5.0, min(20.0, abs(relative) * 60.0))
    return Finding(
        dedup_key="planning/meeting-buffer",
        facts={
            "buffer_text": fmt_minutes(buffer_min),
            "change": fmt_pct(abs(relative)),
            "n": int(ctx["post_meeting_n"]),
        },
        evidence=Evidence(
            basis="matched_pairs", n=int(ctx["post_meeting_n"]),
            effect=abs(relative) * 5,
            comparison="the same hour-of-week on meeting-free days",
        ),
    )


@rule(
    id="PL-05", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"baseline.run_len.p75", "baseline.run_len.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="Break roughly every {cadence_text}",
    why="Your runs typically end around there on their own. Breaking before "
        "that point rather than after it is what keeps the next block intact.",
    action="Set the break at {cadence_text} rather than waiting for attention "
           "to fade.",
)
def break_cadence(ctx: FeatureContext) -> Finding | None:
    cadence = ctx["baseline.run_len.p75"]
    if cadence < 20:
        return None
    return Finding(
        dedup_key="planning/break-cadence",
        facts={"cadence_text": fmt_minutes(cadence)},
        evidence=Evidence(
            basis="personal_p75", n=int(ctx["baseline.run_len.n"]),
            comparison="your 30-day run lengths",
        ),
    )


@rule(
    id="PL-06", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"baseline.stop_hour.p50", "baseline.stop_hour.p90",
              "baseline.stop_hour.n"},
    min_days=10, min_n=8, cooldown=DAY,
    title="A realistic shutdown time is {stop_text}",
    why="Half your days already end by then, and the ones running past "
        "{late_text} are the outliers rather than the norm.",
    action="Deciding the stop time in advance is what stops the day expanding "
           "to fill whatever is left of it.",
)
def shutdown_time(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="planning/shutdown",
        facts={
            "stop_text": fmt_clock(ctx["baseline.stop_hour.p50"]),
            "late_text": fmt_clock(ctx["baseline.stop_hour.p90"]),
        },
        evidence=Evidence(
            basis="personal_median", n=int(ctx["baseline.stop_hour.n"]),
            comparison="your 30-day stop times",
        ),
    )


@rule(
    id="PL-07", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"learn_share", "learn_share_usual", "peak_hour_top"},
    min_days=14, cooldown=DAY,
    title="Book a learning block",
    why="Learning took {actual} of today against a usual {usual}. It is the "
        "first thing a busy day drops and the last thing it misses.",
    action="A short slot near {peak_range} costs less than trying to find the "
           "time later in the day.",
)
def learning_block(ctx: FeatureContext) -> Finding | None:
    actual, usual = ctx["learn_share"], ctx["learn_share_usual"]
    # Only when the usual share is high enough that its absence is a change,
    # and only when today is meaningfully below it.
    if usual < 0.08 or actual >= usual * 0.5:
        return None
    return Finding(
        dedup_key="planning/learning",
        facts={
            "actual": fmt_pct(actual),
            "usual": fmt_pct(usual),
            "peak_range": fmt_hour_range(ctx["peak_hour_top"]),
        },
        evidence=Evidence(
            basis="personal_mix", n=int(ctx.num("baseline.focus.n")),
            effect=(usual - actual) * 10,
            comparison="your 30-day category split",
        ),
    )


@rule(
    id="PL-08", version=1, scope=DAILY, section=Section.PLANNING,
    severity=Severity.LOW,
    requires={"switch_pair_a", "switch_pair_b", "switch_pair_count"},
    min_days=7, cooldown=DAY,
    title="Separate {app_a} and {app_b}",
    why="You moved between them {count} times today — more than any other "
        "pair. Each crossing is a change of context, not just a change of "
        "window.",
    action="Do everything one of them is for in a single pass, then switch "
           "once.",
)
def batch_switch_pair(ctx: FeatureContext) -> Finding | None:
    count = ctx["switch_pair_count"]
    if count < 10:
        return None
    return Finding(
        dedup_key="planning/batch-pair",
        facts={
            "app_a": ctx["switch_pair_a"],
            "app_b": ctx["switch_pair_b"],
            "count": int(count),
        },
        evidence=Evidence(basis="absolute", n=int(count), effect=count / 10.0),
    )
