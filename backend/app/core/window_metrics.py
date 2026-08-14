"""Shared SQL expressions for derived activity_window_10m metrics."""

AVG_FOCUS_SCORE_SQL = """
CASE
    WHEN COALESCE(sum_focus_duration, 0) > 0
        THEN sum_focus_weighted / sum_focus_duration
    ELSE COALESCE(avg_focus_score, 0)
END
""".strip()
