# window_pattern_analysis.py
"""
Pattern‑analysis service that works on the 10‑minute window table
(activity_window_10m) instead of the .npy/.json feature cache.

It re‑uses the exact same HDBSCAN + IsolationForest logic from
PatternAnalysisService – only the way we obtain X and the IDs is different.
"""

from __future__ import annotations

import logging
from typing import List

import numpy as np
from sqlalchemy import text

from app.core.database import SessionLocal
from app.core.config import settings
from app.core.window_metrics import AVG_FOCUS_SCORE_SQL
from app.services.pattern_analysis import PatternAnalysisService
from app.models.db import ActivitySegmentPattern   # reuse the same ORM model for output

logger = logging.getLogger(__name__)


class WindowPatternAnalysisService(PatternAnalysisService):
    """
    Variant of PatternAnalysisService that reads features from the
    activity_window_10m table and writes the results back into the same
    table (adding cluster_id and anomaly_score columns).
    """

    # ------------------------------------------------------------------
    # Constructor – we still accept the same arguments, but we ignore the
    # feature_dir argument because we always pull the data from the DB.
    # ------------------------------------------------------------------
    def __init__(
        self,
        feature_dir: str | None = None,          # ignored – we use the DB
        model_version: str | None = None,
        hdbscan_min_cluster_size: int | None = None,
        hdbscan_min_samples: int | None = None,
        isolation_forest_estimators: int = None,
        isolation_forest_contamination: str | float = "auto",
    ):
        # Call the parent init – it will set model_version, estimators, etc.
        super().__init__(
            feature_dir=feature_dir,
            model_version=model_version,
            hdbscan_min_cluster_size=hdbscan_min_cluster_size,
            hdbscan_min_samples=hdbscan_min_samples,
            isolation_forest_estimators=isolation_forest_estimators,
            isolation_forest_contamination=isolation_forest_contamination,
        )
        # Override the logger message so we know we are using the window table
        logger.info(
            f"WindowPatternAnalysisService initialized – "
            f"model_version={self.model_version}"
        )

    # ------------------------------------------------------------------
    # We do NOT need the .npy detection logic – we always read from DB.
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_latest_feature_dir() -> Path:   # pragma: no cover
        # This method exists only to satisfy the parent class signature.
        # It will never be called because we supply our own load_stored_features.
        raise NotImplementedError(
            "WindowPatternAnalysisService does not use .npy feature files."
        )

    # ------------------------------------------------------------------
    # Override: load X (feature matrix) and the ordered list of IDs from
    # the activity_window_10m table.
    # ------------------------------------------------------------------
    def load_stored_features(self) -> None:
        """
        Reads the feature matrix from activity_window_10m.
        The order of columns in X must match the order used later in
        train_models/predict (any order works as long as it is consistent).
        """
        # ----- 1️⃣  Decide which columns become features -----
        # Feel free to add/remove columns here; just keep the same order
        # when you build the matrix.
        feature_columns: List[str] = [
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

        # ----- 2️⃣  Pull the data from the DB -----
        with SessionLocal() as session:
            cols_sql = ", ".join(feature_columns)
            stmt = f"""
                SELECT window_id, {cols_sql}
                FROM activity_window_10m
                ORDER BY window_start
            """
            # fetchall returns a list of Row objects (thanks to row_factory)
            rows = session.execute(text(stmt)).fetchall()

            if not rows:
                raise RuntimeError(
                    "No rows found in activity_window_10m – "
                    "did the window‑creation script run?"
                )

            # Split IDs and feature values
            self.segment_ids: List[str] = [r[0] for r in rows]   # list of strings
            X = np.array(
                [[float(v) for v in r[1:]] for r in rows],
                dtype=np.float32,
            )

        # ----- 3️⃣  Store them where the parent class expects them -----
        self.feature_matrix = X
        # No scaling parameters are needed for the window features,
        # but we keep the attribute for compatibility.
        self.scaler_params = None

        logger.info(
            f"Loaded window features: {X.shape[0]} samples, "
            f"{X.shape[1]} features from activity_window_10m"
        )
        logger.debug(f"First 5 window IDs: {self.segment_ids[:5]}")

    # ------------------------------------------------------------------
    # Override save_results so we write back into activity_window_10m
    # instead of the segment_patterns table.
    # ------------------------------------------------------------------
    def save_results(self, session: SessionLocal | None = None) -> None:
        """
        Writes cluster_id and anomaly_score back into the
        activity_window_10m table, matched by window_id.
        """
        if self.segment_ids is None or self.cluster_labels is None or self.anomaly_scores is None:
            raise RuntimeError("Model not trained. Call run() or train_models() first.")
        if len(self.cluster_labels) != len(self.segment_ids):
            raise ValueError("Length of cluster_labels does not match number of windows.")
        if len(self.anomaly_scores) != len(self.segment_ids):
            raise ValueError("Length of anomaly_scores does not match number of windows.")

        close_after = False
        if session is None:
            session = SessionLocal()
            close_after = True

        try:
            # Build a list of dicts for a bulk UPDATE
            updates = []
            for win_id, cl, ascore in zip(self.segment_ids, self.cluster_labels, self.anomaly_scores):
                updates.append(
                    {
                        "window_id": win_id,
                        "cluster_id": int(cl) if cl != -1 else None,   # store NULL for noise
                        "anomaly_score": float(ascore),
                    }
                )

            # Perform a bulk update using SQLite’s UPDATE … FROM (VALUES …) syntax.
            # This works with SQLite 3.35+. If you are on an older version,
            # fall back to a row‑by‑row UPDATE inside a loop (still fast for a few‑k rows).
            case_vals = " ".join(
                f"WHEN '{u['window_id']}' THEN {u['cluster_id'] if u['cluster_id'] is not None else 'NULL'}"
                for u in updates
            )
            case_vals_score = " ".join(
                f"WHEN '{u['window_id']}' THEN {u['anomaly_score']}"
                for u in updates
            )
            update_sql = f"""
                UPDATE activity_window_10m
                SET
                    cluster_id = CASE window_id {case_vals} END,
                    anomaly_score = CASE window_id {case_vals_score} END
                WHERE window_id IN ({",".join(f"'{u['window_id']}'" for u in updates)});
            """
            session.execute(text(update_sql))
            session.commit()
            logger.info(
                f"Updated {len(updates)} rows in activity_window_10m with clustering results "
                f"(model_version={self.model_version})"
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to save window‑level pattern analysis results")
            raise
        finally:
            if close_after:
                session.close()

    # ------------------------------------------------------------------
    # The run() method from the parent class works unchanged:
    #   load_stored_features → train_models → predict → save_results
    # ------------------------------------------------------------------


# ----------------------------------------------------------------------
# Allow running the file directly for quick testing
# ----------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    service = WindowPatternAnalysisService()
    service.run()
