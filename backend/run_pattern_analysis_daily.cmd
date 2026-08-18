@echo off
cd /d "%~dp0"

REM The Scheduled Task console is cp1252; without this a single non-ASCII
REM character in any print() aborts the run before it writes anything.
set PYTHONIOENCODING=utf-8

REM Two stages, in order. This task used to run only the second one, so it
REM clustered whatever windows already existed and never rebuilt them --
REM Insights kept re-analysing stale data as new activity arrived.
REM   1. rebuild activity_window_10m from activity_segments (+ additive cols)
REM   2. cluster those windows into activity_window_patterns
REM   3. recompute personal baselines and run the period rule families
".\venv\Scripts\python.exe" refresh_windows_nightly.py
if errorlevel 1 (
    echo [%date% %time%] window rebuild failed; skipping clustering to avoid
    echo   writing patterns from a half-built window table.
    exit /b 1
)

".\venv\Scripts\python.exe" run_pattern_analysis.py
if errorlevel 1 (
    echo [%date% %time%] clustering failed; skipping recommendations, which
    echo   read the patterns it was supposed to write.
    exit /b 1
)

REM Stage 3 was documented above but never actually invoked, so the daily,
REM weekly and monthly rule families never ran -- only the LIVE family, from
REM the 60-second job inside the backend process.
".\venv\Scripts\python.exe" run_recommendations.py
exit /b %errorlevel%
