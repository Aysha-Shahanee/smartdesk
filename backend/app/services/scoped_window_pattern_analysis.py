from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from app.core.database import SessionLocal
from app.core.time import completed_day_range, local_day_start
from app.core.window_metrics import AVG_FOCUS_SCORE_SQL
from app.models.db import ActivityWindowPatternRecord

logger = logging.getLogger(__name__)

PatternScope = Literal["day", "week", "month"]

# Cut points on avg_focus_score (0..1), used only when clustering degenerates
# into fewer than three clusters and there is no relative ranking to read.
LOW_FOCUS_MAX = 0.25
HIGH_FOCUS_MIN = 0.55


@dataclass(frozen=True)
class ScopeRun:
    scope: PatternScope
    run_date: str
    range_from: datetime
    range_to: datetime
    model_version: str


def compute_scope_runs(run_at: datetime) -> list[ScopeRun]:
    local_run = run_at.astimezone(run_at.tzinfo) if run_at.tzinfo else run_at
    day_start = local_day_start(local_run)
    run_date = day_start.date().isoformat()
    model_stamp = local_run.strftime("%Y%m%dT%H%M%S")

    runs = [
        ScopeRun(
            scope="day",
            run_date=run_date,
            range_from=completed_day_range(1, local_run)[0],
            range_to=completed_day_range(1, local_run)[1],
            model_version=f"day_{model_stamp}",
        )
    ]

    if day_start.weekday() == 0:
        start, end = completed_day_range(7, local_run)
        runs.append(
            ScopeRun(
                scope="week",
                run_date=run_date,
                range_from=start,
                range_to=end,
                model_version=f"week_{model_stamp}",
            )
        )

    if day_start.day == 1:
        start, end = completed_day_range(30, local_run)
        runs.append(
            ScopeRun(
                scope="month",
                run_date=run_date,
                range_from=start,
                range_to=end,
                model_version=f"month_{model_stamp}",
            )
        )

    return runs


class ScopedWindowPatternAnalysisService:
    FEATURE_COLUMNS = [
        "active_seconds", "idle_seconds",
        "active_ratio", "idle_ratio",
        "app_switches", "category_switches",
        "unique_apps",
        "work_ratio", "learn_ratio", "communication_ratio",
        "entertainment_ratio", "documentation_ratio",
        "system_ratio", "other_ratio",
        "longest_continuous_seconds",
        f"{AVG_FOCUS_SCORE_SQL} AS avg_focus_score",
    ]

    def __init__(self, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory

    def run_scope(self, scope_run: ScopeRun) -> int:
        with self._session_factory() as session:
            windows = self._load_windows(session, scope_run)
            if len(windows) < 3:
                logger.info(
                    "Skipping %s scope for %s: only %d windows in range %s -> %s",
                    scope_run.scope,
                    scope_run.run_date,
                    len(windows),
                    scope_run.range_from.isoformat(),
                    scope_run.range_to.isoformat(),
                )
                return 0

            labels, scores = self._cluster(windows)
            focus_levels = self._label_focus_levels(labels, windows)
            self._upsert_results(session, scope_run, windows, labels, scores, focus_levels)
            logger.info(
                "Stored %d %s-scope window pattern rows for %s",
                len(windows),
                scope_run.scope,
                scope_run.run_date,
            )
            return len(windows)

    def _load_windows(self, session: Session, scope_run: ScopeRun) -> list[dict]:
        cols_sql = ", ".join(["window_id", "window_start", "window_end", *self.FEATURE_COLUMNS])
        query = text(f"""
            SELECT {cols_sql}
            FROM activity_window_10m
            WHERE window_start >= :range_from
              AND window_start < :range_to
            ORDER BY window_start
        """)
        rows = session.execute(query, {
            "range_from": scope_run.range_from.strftime("%Y-%m-%d %H:%M:%S"),
            "range_to": scope_run.range_to.strftime("%Y-%m-%d %H:%M:%S"),
        }).mappings().all()
        return [dict(row) for row in rows]

    def _cluster(self, windows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
        feature_names = [
            "active_seconds", "idle_seconds", "active_ratio", "idle_ratio",
            "app_switches", "category_switches", "unique_apps",
            "work_ratio", "learn_ratio", "communication_ratio",
            "entertainment_ratio", "documentation_ratio", "system_ratio", "other_ratio",
            "longest_continuous_seconds", "avg_focus_score",
        ]
        X = np.array([[float(window[name]) for name in feature_names] for window in windows], dtype=np.float32)
        X_scaled = StandardScaler().fit_transform(X)

        kmeans = KMeans(
            n_clusters=3,
            init="k-means++",
            n_init="auto",
            max_iter=300,
            random_state=42,
        )
        labels = kmeans.fit_predict(X_scaled)

        iso = IsolationForest(
            n_estimators=100,
            contamination="auto",
            random_state=42,
            n_jobs=1,
        )
        scores = iso.fit(X_scaled).decision_function(X_scaled)
        return labels, scores

    def _label_focus_levels(self, labels: np.ndarray, windows: list[dict]) -> dict[int, str]:
        cluster_scores: dict[int, list[float]] = {}
        for label, window in zip(labels, windows):
            cluster_scores.setdefault(int(label), []).append(float(window["avg_focus_score"]))

        ranked = sorted(
            ((cluster, sum(scores) / len(scores)) for cluster, scores in cluster_scores.items()),
            key=lambda item: item[1],
            reverse=True,
        )
        if len(ranked) < 3:
            # The three levels are assigned by rank, which needs three clusters
            # to rank. KMeans returns fewer whenever a range's windows are
            # near-identical — an untouched machine produces a day of 144
            # all-zero rows that collapse to one cluster — and calling every
            # one of those "high_focus" reported dead days as the user's best.
            # With nothing to rank against, score each surviving cluster on its
            # own average, which is what the level names claim to describe.
            return {cluster: self._absolute_focus_level(score) for cluster, score in ranked}

        return {
            ranked[0][0]: "high_focus",
            ranked[-1][0]: "low_focus",
            ranked[1][0]: "distracted",
        }

    @staticmethod
    def _absolute_focus_level(score: float) -> str:
        if score < LOW_FOCUS_MAX:
            return "low_focus"
        if score >= HIGH_FOCUS_MIN:
            return "high_focus"
        return "distracted"

    def _upsert_results(
        self,
        session: Session,
        scope_run: ScopeRun,
        windows: list[dict],
        labels: np.ndarray,
        scores: np.ndarray,
        focus_levels: dict[int, str],
    ) -> None:
        for window, label, score in zip(windows, labels, scores):
            existing = session.query(ActivityWindowPatternRecord).filter(
                ActivityWindowPatternRecord.window_id == window["window_id"],
                ActivityWindowPatternRecord.scope == scope_run.scope,
            ).first()

            values = {
                "window_start": window["window_start"],
                "window_end": window["window_end"],
                "run_date": scope_run.run_date,
                "range_from": scope_run.range_from,
                "range_to": scope_run.range_to,
                "cluster_id": int(label),
                "focus_level": focus_levels[int(label)],
                "anomaly_score": float(score),
                "avg_focus_score": float(window["avg_focus_score"]),
                "work_ratio": float(window["work_ratio"]),
                "learn_ratio": float(window["learn_ratio"]),
                "communication_ratio": float(window["communication_ratio"]),
                "model_version": scope_run.model_version,
            }

            if existing:
                for key, value in values.items():
                    setattr(existing, key, value)
            else:
                session.add(ActivityWindowPatternRecord(
                    id=str(uuid.uuid4()),
                    window_id=window["window_id"],
                    scope=scope_run.scope,
                    **values,
                ))

        session.commit()
