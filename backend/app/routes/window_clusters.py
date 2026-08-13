"""Endpoint for retrieving scoped window cluster data."""

from typing import Dict, List, Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.database import get_db

router = APIRouter()


@router.get("/window-clusters")
def get_window_clusters(
    limit: int = Query(200, gt=0, le=1000, description="Maximum number of recent windows to return"),
    date: str | None = None,
    scope: str = "day",
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    Retrieve recent window clusters with focus levels, cluster IDs, and anomaly scores.

    Returns JSON suitable for frontend consumption, showing the most recent windows
    ordered by window_start descending.
    """
    query = text("""
        SELECT
            window_start,
            window_end,
            window_id,
            focus_level,
            cluster_id,
            anomaly_score,
            work_ratio,
            learn_ratio,
            communication_ratio,
            avg_focus_score
        FROM activity_window_patterns
        WHERE scope = :scope
          AND (
            (:date IS NOT NULL AND substr(window_start, 1, 10) = :date)
            OR (
                :date IS NULL
                AND run_date = (
                    SELECT MAX(run_date)
                    FROM activity_window_patterns
                    WHERE scope = :scope
                )
            )
          )
        ORDER BY window_start DESC
        LIMIT :limit
    """)

    result = db.execute(query, {"limit": limit, "date": date, "scope": scope})
    rows = result.fetchall()

    # Convert rows to list of dictionaries
    window_clusters = []
    for row in rows:
        window_clusters.append({
            "window_start": row.window_start,
            "window_end": row.window_end,
            "window_id": row.window_id,
            "focus_level": row.focus_level,
            "cluster_id": row.cluster_id,
            "anomaly_score": float(row.anomaly_score) if row.anomaly_score is not None else None,
            "work_ratio": row.work_ratio,
            "learn_ratio": row.learn_ratio,
            "communication_ratio": row.communication_ratio,
            "avg_focus_score": row.avg_focus_score,
        })

    return window_clusters
