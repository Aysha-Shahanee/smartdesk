# Task-specific Time Spent

SmartDesk calculates task Time Spent from persisted development activity rather
than wall-clock duration. The OS collector determines active/idle boundaries,
the IDE collector identifies the GitHub repository being worked on, and only
foreground active intervals matching exactly one active GitHub lifecycle in
that repository are counted. Idle, locked, gap, background-AI-only,
unrelated-repository, and ambiguous intervals are excluded. Qualifying
intervals are clipped to the lifecycle and merged before summation to prevent
double counting.

## Existing timing reused

- The OS collector polls Windows user-input and foreground state every 1 second
  by default (`SMARTDESK_POLL_INTERVAL`) and declares idle after 120 seconds by
  default (`SMARTDESK_IDLE_THRESHOLD`).
- The VS Code extension updates its existing IDE session with a cumulative
  heartbeat every 45 seconds. Its local idle threshold is 120 seconds, checked
  every 30 seconds.
- The existing activity-segment builder runs every 5 minutes, holds back the
  latest 30 seconds for late events, and resumes from its persisted watermark
  after restart.
- The Prediction page refreshes `/active-tasks` every 15 seconds.

Time Spent introduces no new collection window, collector, timer, or scheduler.
It consumes the activity segments produced by the existing activity pipeline,
so authoritative values update when those persisted segments become available.

## Attribution and data gaps

IDE sessions retain the existing hashed `repo_id` and additionally store a
canonical lowercase GitHub `owner/repository`, derived only from an HTTPS, SSH,
or SCP-like `github.com` origin. Missing and non-GitHub remotes remain null.
Historical hashes are not reversed.

If exactly one active lifecycle matches the IDE repository, its qualifying time
is attributed by repository. If none matches, the result is `no_match`. If more
than one active lifecycle has that repository, the result is `ambiguous` and no
time is assigned. Missing collector coverage is never reconstructed from
lifecycle wall-clock duration. `data_status` reports `complete`, `partial`, or
`unavailable` based on the repository-bearing persisted intervals seen by the
calculation.

Background AI sessions remain useful future progress signals, but are excluded
from Phase 1 human Time Spent because they do not represent confirmed developer
active time.

## Status-aware Remaining Estimate baseline

SmartDesk first produces an initial task-duration estimate when the GitHub task
becomes active. It then calculates task-specific Time Spent from persisted
foreground IDE-active intervals. Remaining Estimate is a transparent baseline
while the task has not exhausted its initial estimate:

```text
if time_spent_hours < predicted_typical_hours:
    remaining_time_hours = predicted_typical_hours - time_spent_hours
    remaining_time_status = "baseline_available"

if time_spent_hours >= predicted_typical_hours and the task remains ACTIVE:
    remaining_time_hours = null
    remaining_time_status = "estimate_exceeded"
    overrun_hours = time_spent_hours - predicted_typical_hours

if the task is DONE:
    remaining_time_hours = 0
    remaining_time_status = "completed"
```

The backend derives this value whenever `/active-tasks` is requested. It is not
decremented by an in-memory timer and has no database accumulator, so closing
the frontend or restarting SmartDesk does not reset it. The Prediction page may
poll every 15 seconds, but the value changes only when the existing activity
pipeline persists new authoritative Time Spent.

Subtraction occurs only for a complete `repository_match`. Ambiguous, missing,
or partial Time Spent and missing initial predictions make Remaining Estimate
unavailable; unknown Time Spent is never treated as zero. The lower bound is
zero. An ACTIVE task that reaches or exceeds its estimate does not display zero
remaining: it displays no numeric Remaining Estimate and reports the overrun.
At 90% of the initial estimate it may display `Approaching initial estimate`;
this warning is not a completion probability or progress percentage.

This method assumes the initial estimate approximates total work and that each
attributed active IDE hour represents progress against it. It is a baseline,
not a calibrated completion forecast: the initial model was trained on
first-commit-to-merge duration, which includes review and waiting time, while
Time Spent measures active IDE work. A future checkpoint model may address that
measurement mismatch; no ML model is changed by this baseline.
