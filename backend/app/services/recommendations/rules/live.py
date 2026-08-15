"""Family A — live rules, evaluated every 60 seconds.

Each one is a pure predicate over the feature snapshot: no database, no clock,
no I/O. That is what lets the whole family run in well under a millisecond and
what makes each rule testable from a dictionary.
"""

from __future__ import annotations

from datetime import timedelta

from app.services.recommendations.narrative import (
    fmt_clock,
    fmt_hour_range,
    fmt_minutes,
    fmt_ratio,
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

LIVE = Scope.LIVE
DISTRACTION = ("entertainment", "social_media")


# --------------------------------------------------------------------- #
# Sustained attention and breaks                                          #
# --------------------------------------------------------------------- #

@rule(
    id="LV-01", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"active_run_min", "baseline.run_len.p90", "baseline.run_len.n"},
    min_days=7, min_n=8, cooldown=timedelta(minutes=90),
    action_label="Start Break",
    title="Take a break — {run_text} without stopping",
    why="You have been active for {run_text} without a break. Your own runs "
        "usually end by {limit_text}, so this one is already past where your "
        "attention normally holds.",
    action="Step away for five minutes. Your work context is saved and will be "
           "waiting on {app}.",
)
def unbroken_stretch(ctx: FeatureContext) -> Finding | None:
    # Floor of 75 minutes: below that a break prompt is noise however short
    # this user's typical run happens to be. The personal percentile only ever
    # raises the bar, never lowers it beneath usefulness.
    limit = max(75.0, ctx["baseline.run_len.p90"])
    run = ctx["active_run_min"]
    if run < limit:
        return None
    return Finding(
        dedup_key="break/needed",
        facts={
            "run_text": fmt_minutes(run),
            "limit_text": fmt_minutes(limit),
            "app": ctx.get("current_app") or "your last app",
        },
        evidence=Evidence(
            basis="personal_p90", n=int(ctx["baseline.run_len.n"]),
            effect=run - limit, comparison="your 30-day run lengths",
        ),
        severity=Severity.HIGH if run >= limit * 1.5 else Severity.MEDIUM,
    )


@rule(
    id="LV-17", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"minutes_since_break"}, cooldown=timedelta(hours=3),
    action_label="Start Break",
    title="No real break in {since_text}",
    why="Nothing longer than a five-minute pause has interrupted the last "
        "{since_text} of activity.",
    action="A short walk now costs five minutes and usually buys back more "
           "than that in the next hour.",
)
def no_break_today(ctx: FeatureContext) -> Finding | None:
    since = ctx["minutes_since_break"]
    if since < 180:
        return None
    return Finding(
        dedup_key="break/needed",
        facts={"since_text": fmt_minutes(since)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-02", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"today_active_min", "baseline.daily_active_min.p90",
              "baseline.daily_active_min.n"},
    min_days=10, min_n=8, cooldown=timedelta(hours=6),
    title="Long day — {total_text} already",
    why="That is more screen time than on 90% of your recorded days, where "
        "you would normally be at {p90_text} by the end of the day.",
    action="Consider what still genuinely needs doing today and let the rest "
           "start tomorrow.",
)
def long_screen_day(ctx: FeatureContext) -> Finding | None:
    total = ctx["today_active_min"]
    p90 = ctx["baseline.daily_active_min.p90"]
    # A floor as well as a percentile: on a lightly-tracked history the p90
    # can sit at ninety minutes, and telling someone they have had a long day
    # after ninety minutes would be absurd regardless of what their own
    # distribution says.
    if total < max(p90, 240.0):
        return None
    return Finding(
        dedup_key="load/long-day",
        facts={"total_text": fmt_minutes(total), "p90_text": fmt_minutes(p90)},
        evidence=Evidence(
            basis="personal_p90", n=int(ctx["baseline.daily_active_min.n"]),
            effect=total - p90, comparison="your 30-day daily totals",
        ),
    )


@rule(
    id="LV-15", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"session_hour_now", "session_run_min",
              "baseline.stop_hour.p90", "baseline.stop_hour.n"},
    min_days=10, min_n=8, cooldown=timedelta(hours=4),
    title="Past when you normally stop",
    why="You have usually finished by {stop_text}; this session has been "
        "running {run_text}. Focus in your late hours averages {late_focus} "
        "of your daytime best.",
    action="Note where you are and pick it up tomorrow — the last hour of a "
           "long day rarely earns its keep.",
)
def past_stop_time(ctx: FeatureContext) -> Finding | None:
    # Both sides on the continuous session scale, so 01:00 continuing last
    # night's session reads as 25.0 rather than sorting below every daytime
    # hour. The previous clock comparison needed a `now < 20` guard to avoid
    # firing at 09:00, and that guard also silenced the rule for exactly the
    # small-hours sessions it most wanted to catch.
    now = ctx["session_hour_now"]
    stop = ctx["baseline.stop_hour.p90"]
    if now < stop:
        return None
    peak = ctx.get("baseline.focus.p75")
    hour_focus = ctx.get("hour_focus_now")
    late_focus = (
        f"{round(hour_focus / peak * 100)}%"
        if peak and hour_focus and peak > 0 else "below"
    )
    return Finding(
        dedup_key="load/late",
        facts={
            "stop_text": fmt_clock(stop),
            "run_text": fmt_minutes(ctx["session_run_min"]),
            "late_focus": late_focus,
        },
        evidence=Evidence(
            basis="personal_p90", n=int(ctx["baseline.stop_hour.n"]),
            comparison="your 30-day stop times",
        ),
    )


# --------------------------------------------------------------------- #
# Fragmentation                                                           #
# --------------------------------------------------------------------- #

@rule(
    id="LV-03", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.HIGH,
    requires={"switch_rate_15m", "baseline.switch_rate.p90", "baseline.switch_rate.n"},
    min_days=7, min_n=8, cooldown=timedelta(minutes=45),
    title="You are switching apps {ratio} faster than usual",
    why="{rate} app changes a minute over the last quarter hour, against a "
        "typical busy stretch of {p90}. Attention is being spread thin rather "
        "than moved deliberately.",
    action="Pick the one thing that matters most right now and close the rest "
           "for twenty minutes.",
)
def switch_storm(ctx: FeatureContext) -> Finding | None:
    rate = ctx["switch_rate_15m"]
    p90 = ctx["baseline.switch_rate.p90"]
    if rate <= 0 or rate < max(p90, 0.4):
        return None
    return Finding(
        dedup_key="fragmentation/now",
        facts={
            "rate": f"{rate:.1f}",
            "p90": f"{p90:.1f}",
            "ratio": fmt_ratio(rate / p90) if p90 > 0 else "much",
        },
        evidence=Evidence(
            basis="personal_p90", n=int(ctx["baseline.switch_rate.n"]),
            effect=rate - p90, comparison="your 30-day switch rates",
        ),
    )


@rule(
    id="LV-04", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"category_switches_10m", "baseline.category_switches.p90",
              "baseline.category_switches.n"},
    min_days=7, min_n=8, cooldown=timedelta(minutes=45),
    title="Jumping between different kinds of work",
    why="{count} changes of activity type in ten minutes, where {p90} is "
        "already a busy stretch for you. Each change costs more than a switch "
        "within the same kind of work.",
    action="Group the similar tasks together and do them in one pass.",
)
def category_churn(ctx: FeatureContext) -> Finding | None:
    count = ctx["category_switches_10m"]
    p90 = ctx["baseline.category_switches.p90"]
    if count < max(p90, 4.0):
        return None
    return Finding(
        dedup_key="fragmentation/now",
        facts={"count": int(count), "p90": int(p90)},
        evidence=Evidence(
            basis="personal_p90", n=int(ctx["baseline.category_switches.n"]),
            comparison="your 30-day category switching",
        ),
    )


@rule(
    id="LV-05", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.LOW,
    requires={"unique_domains_10m"}, cooldown=timedelta(hours=1),
    title="{count} different sites in ten minutes",
    why="Research that spreads this wide usually means the question has not "
        "been pinned down yet.",
    action="Write the question you are actually trying to answer in one line, "
           "then look for that.",
)
def tab_sprawl(ctx: FeatureContext) -> Finding | None:
    # Absolute rather than personal: browser domains are not in the window
    # roll-up, so there is no stored distribution to compare against yet. Six
    # distinct hosts inside ten minutes is above anything a single task
    # produces in the recorded browser history.
    count = ctx["unique_domains_10m"]
    if count < 6:
        return None
    return Finding(
        dedup_key="fragmentation/browsing",
        facts={"count": int(count)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-18", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"repeat_context_count", "repeat_context_title"},
    cooldown=timedelta(hours=2),
    title="You keep coming back to the same thing",
    why="\"{title}\" has been picked up {count} times in the last few hours "
        "without being finished.",
    action="Either give it one uninterrupted block now, or write down what is "
           "blocking it and put it away.",
)
def repeat_context(ctx: FeatureContext) -> Finding | None:
    count = ctx["repeat_context_count"]
    if count < 5:
        return None
    return Finding(
        dedup_key="fragmentation/reentry",
        facts={"count": int(count), "title": ctx["repeat_context_title"]},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-19", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.LOW,
    requires={"navigation_min_30m"}, cooldown=timedelta(hours=3),
    title="{mins_text} looking for files",
    why="File Explorer and system windows have taken {mins_text} of the last "
        "half hour. That normally means something is not where you expect it.",
    action="Worth a minute to bookmark or reorganise the folder you keep "
           "returning to.",
)
def navigation_friction(ctx: FeatureContext) -> Finding | None:
    mins = ctx["navigation_min_30m"]
    if mins < 12:
        return None
    return Finding(
        dedup_key="friction/navigation",
        facts={"mins_text": fmt_minutes(mins)},
        evidence=Evidence(basis="absolute"),
    )


# --------------------------------------------------------------------- #
# Distraction                                                             #
# --------------------------------------------------------------------- #

@rule(
    id="LV-06", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.HIGH,
    requires={"entertainment_run_min"}, cooldown=timedelta(hours=2),
    title="{run_text} straight on {app}",
    why="This has been one unbroken stretch of {category} during your normal "
        "working hours.",
    action="If it was meant to be a short break, now is the moment it stops "
           "being one.",
)
def distraction_run(ctx: FeatureContext) -> Finding | None:
    run = ctx["entertainment_run_min"]
    if run < 20:
        return None
    category = ctx.get("current_category")
    if category not in DISTRACTION:
        return None
    return Finding(
        dedup_key="distraction/now",
        facts={
            "run_text": fmt_minutes(run),
            "app": ctx.get("current_app") or "it",
            "category": "entertainment" if category == "entertainment" else "social media",
        },
        evidence=Evidence(basis="absolute"),
        severity=Severity.HIGH if run >= 45 else Severity.MEDIUM,
    )


@rule(
    id="LV-07", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"social_min_this_hour"}, cooldown=timedelta(hours=1),
    title="{mins_text} of this hour has gone to distractions",
    why="Spread across several visits rather than one block, which is the "
        "pattern that is hardest to notice while it is happening.",
    action="Close the tab rather than switching away from it.",
)
def distraction_accumulating(ctx: FeatureContext) -> Finding | None:
    mins = ctx["social_min_this_hour"]
    if mins < 20:
        return None
    return Finding(
        dedup_key="distraction/now",
        facts={"mins_text": fmt_minutes(mins)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-16", version=1, scope=LIVE, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"day_first_category", "day_start_hour"}, cooldown=timedelta(hours=12),
    title="The day started on a distraction",
    why="Your first activity today at {start_text} was {category}. Days that "
        "open this way tend to take longer to find a rhythm.",
    action="Tomorrow, open the one thing you most want finished before "
           "anything else.",
)
def day_opened_distracted(ctx: FeatureContext) -> Finding | None:
    if ctx["day_first_category"] not in DISTRACTION:
        return None
    return Finding(
        dedup_key="pattern/day-open",
        facts={
            "start_text": f"{int(ctx['day_start_hour']):02d}:00",
            "category": ctx["day_first_category"].replace("_", " "),
        },
        evidence=Evidence(basis="absolute"),
    )


# --------------------------------------------------------------------- #
# Focus state                                                             #
# --------------------------------------------------------------------- #

@rule(
    id="LV-08", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"recent_focus", "baseline.focus.p25", "baseline.focus.n"},
    min_days=7, min_n=8, cooldown=timedelta(hours=1),
    title="Focus has been slipping for half an hour",
    why="The last thirty minutes score {score} against your usual floor of "
        "{p25}. Something is fragmenting the work rather than the work being "
        "hard.",
    action="Change one thing — close a window, move rooms, or take the break "
           "early.",
)
def focus_sliding(ctx: FeatureContext) -> Finding | None:
    recent = ctx["recent_focus"]
    p25 = ctx["baseline.focus.p25"]
    if recent >= p25:
        return None
    return Finding(
        dedup_key="focus/sliding",
        facts={"score": f"{recent:.2f}", "p25": f"{p25:.2f}"},
        evidence=Evidence(
            basis="personal_p25", n=int(ctx["baseline.focus.n"]),
            effect=p25 - recent, comparison="your 30-day window focus scores",
        ),
    )


@rule(
    id="LV-20", version=1, scope=LIVE, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"recent_focus", "hour_focus_now"}, min_days=10,
    cooldown=timedelta(hours=2),
    title="Unusual for this time of day",
    why="You normally score around {typical} in the {hour_range} hour; right "
        "now it is {actual}.",
    action="Worth noticing what is different about today at this hour.",
)
def unusual_for_hour(ctx: FeatureContext) -> Finding | None:
    recent = ctx["recent_focus"]
    typical = ctx["hour_focus_now"]
    # Half the usual score for this hour, and only when the usual is high
    # enough for the comparison to mean anything.
    if typical < 0.4 or recent >= typical * 0.5:
        return None
    return Finding(
        dedup_key="focus/unusual-hour",
        facts={
            "typical": f"{typical:.2f}",
            "actual": f"{recent:.2f}",
            "hour_range": fmt_hour_range(ctx["now_hour"]),
        },
        evidence=Evidence(
            basis="personal_hour_median", n=int(ctx.num("baseline.focus.n")),
            comparison="the same hour across 30 days",
        ),
    )


@rule(
    id="LV-14", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.LOW,
    requires={"hours_to_peak", "peak_hour_top"}, min_days=10,
    cooldown=timedelta(hours=6),
    title="Your best hour starts soon",
    why="{peak_range} is consistently your strongest stretch across the last "
        "30 days.",
    action="Clear the small tasks now so the hour itself goes to the hard "
           "thing.",
)
def peak_approaching(ctx: FeatureContext) -> Finding | None:
    if ctx["hours_to_peak"] != 1.0:
        return None
    return Finding(
        dedup_key="planning/peak-approaching",
        facts={"peak_range": fmt_hour_range(ctx["peak_hour_top"])},
        evidence=Evidence(
            basis="personal_hour_median", n=int(ctx.num("baseline.focus.n")),
            comparison="hour-of-day focus across 30 days",
        ),
    )


# --------------------------------------------------------------------- #
# IDE                                                                     #
# --------------------------------------------------------------------- #

@rule(
    id="LV-09", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"ide_foreground_min", "ide_edits"}, cooldown=timedelta(hours=1),
    title="The editor has been open but idle",
    why="{mins_text} in the IDE without a single edit. That is usually "
        "reading, being stuck, or having drifted elsewhere.",
    action="If you are stuck, write the problem out in a comment — it is "
           "faster than re-reading.",
)
def stalled_in_ide(ctx: FeatureContext) -> Finding | None:
    mins = ctx["ide_foreground_min"]
    if mins < 15 or ctx["ide_edits"] > 0:
        return None
    return Finding(
        dedup_key="ide/stalled",
        facts={"mins_text": fmt_minutes(mins)},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-10", version=1, scope=LIVE, section=Section.INSIGHT,
    severity=Severity.LOW,
    requires={"ide_edits_per_min"}, cooldown=timedelta(hours=2),
    title="You are in the middle of a good run",
    why="{rate} edits a minute over the last twenty minutes — near the top of "
        "your recorded editing pace.",
    action="Notifications are held back while this lasts.",
)
def edit_burst(ctx: FeatureContext) -> Finding | None:
    # 1.5 edits/min is FocusScorer.EDIT_SATURATION, set from the observed
    # spread across IDE sessions with any editing at all (median 0.74/min,
    # p95 3.43). Reusing it keeps one definition of "dense editing".
    rate = ctx["ide_edits_per_min"]
    if rate < 1.5:
        return None
    return Finding(
        dedup_key="ide/burst",
        facts={"rate": f"{rate:.1f}"},
        evidence=Evidence(basis="absolute"),
    )


# --------------------------------------------------------------------- #
# Meetings and context                                                    #
# --------------------------------------------------------------------- #

@rule(
    id="LV-12", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.HIGH,
    requires={"minutes_to_next_meeting", "next_meeting_title"},
    cooldown=timedelta(minutes=30),
    title="{title} starts in {mins_text}",
    why="You are mid-task; stopping cleanly now costs less than being "
        "interrupted in a few minutes.",
    action="Note where you are so the thread survives the meeting.",
)
def meeting_imminent(ctx: FeatureContext) -> Finding | None:
    mins = ctx["minutes_to_next_meeting"]
    if mins > 10 or mins < 0:
        return None
    return Finding(
        dedup_key="calendar/imminent",
        facts={
            "title": ctx["next_meeting_title"],
            "mins_text": fmt_minutes(mins),
        },
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-13", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.MEDIUM,
    requires={"in_meeting", "current_state", "meeting_title"},
    cooldown=timedelta(minutes=30),
    title="{title} is running but the machine is idle",
    why="The event is in progress and there has been no input for several "
        "minutes.",
    action="If you are in the meeting, nothing to do. If you forgot it, now "
           "you know.",
)
def meeting_but_away(ctx: FeatureContext) -> Finding | None:
    if ctx["current_state"] not in ("idle", "locked"):
        return None
    return Finding(
        dedup_key="calendar/away",
        facts={"title": ctx["meeting_title"]},
        evidence=Evidence(basis="absolute"),
    )


@rule(
    id="LV-11", version=1, scope=LIVE, section=Section.IMMEDIATE,
    severity=Severity.LOW,
    requires={"just_returned", "last_work_title", "last_break_min"},
    cooldown=timedelta(minutes=30),
    action_label="Resume Task",
    title="Pick up where you left off",
    why="You were on \"{title}\" before a {away_text} break.",
    action="Reopen it in {app} and carry on.",
)
def resume_context(ctx: FeatureContext) -> Finding | None:
    return Finding(
        dedup_key="context/resume",
        facts={
            "title": ctx["last_work_title"],
            "away_text": fmt_minutes(ctx["last_break_min"]),
            "app": ctx.get("last_work_app") or "your editor",
        },
        evidence=Evidence(basis="absolute"),
    )
