# pattern_analysis.py
"""
Pattern‑analysis service that works on the .npy/.json feature cache.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List

import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.db import ActivitySegmentPattern

logger = logging.getLogger(__name__)


class PatternAnalysisService:
    def __init__(
        self,
        feature_dir: str | None = None,
        model_version: str | None = None,
        hdbscan_min_cluster_size: int | None = None,
        hdbscan_min_samples: int | None = None,
        isolation_forest_estimators: int = None,
        isolation_forest_contamination: str | float = "auto",
    ):
        self.feature_dir = Path(feature_dir) if feature_dir else None
        self.model_version = model_version or "unknown"
        self.hdbscan_min_cluster_size = hdbscan_min_cluster_size
        self.hdbscan_min_samples = hdbscan_min_samples
        self.isolation_forest_estimators = isolation_forest_estimators
        self.isolation_forest_contamination = isolation_forest_contamination

        self.feature_matrix: np.ndarray | None = None
        self.scaler_params: dict | None = None
        self.segment_ids: List[str] | None = None
        self.kmeans_model: KMeans | None = None
        self.iso_model: IsolationForest | None = None
        self.cluster_labels: np.ndarray | None = None
        self.anomaly_scores: np.ndarray | None = None

        logger.info(
            f"PatternAnalysisService initialized – "
            f"model_version={self.model_version}"
        )

    def _detect_latest_feature_dir(self) -> Path:
        if self.feature_dir is None:
            raise RuntimeError("feature_dir not set")
        # If feature_dir points to a specific version folder, use it.
        # Otherwise, assume it contains timestamped subfolders and pick the newest.
        # For simplicity, we just return the directory itself.
        return self.feature_dir

    def load_stored_features(self) -> None:
        feature_dir = self._detect_latest_feature_dir()
        # Load .npy files: features.npy, ids.json, maybe metadata.json
        X_path = feature_dir / "features.npy"
        ids_path = feature_dir / "ids.json"
        if not X_path.is_file() or not ids_path.is_file():
            raise RuntimeError(f"Feature files not found in {feature_dir}")
        self.feature_matrix = np.load(X_path)
        with open(ids_path) as f:
            self.segment_ids = json.load(f)
        # Optionally load scaler params
        scaler_path = feature_dir / "scaler_params.json"
        if scaler_path.is_file():
            with open(scaler_path) as f:
                self.scaler_params = json.load(f)
        else:
            self.scaler_params = None
        logger.info(
            f"Loaded features: {self.feature_matrix.shape[0]} samples, "
            f"{self.feature_matrix.shape[1]} features from {feature_dir}"
        )
        logger.debug(f"First 5 IDs: {self.segment_ids[:5]}")

    def train_models(self) -> None:
        X = self.feature_matrix
        if X is None:
            raise RuntimeError("Features not loaded. Call load_stored_features first.")
        # Standardise the data
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        # Keep the scaler parameters so we can reuse them later (e.g. in predict)
        self.scaler_params = {
            "mean": scaler.mean_.tolist(),
            "scale": scaler.scale_.tolist()
        }
        # K-Means (K = 3) as requested: strong focus, low focus, distracted
        n_clusters = 3
        self.kmeans_model = KMeans(
            n_clusters=n_clusters,
            init="k-means++",
            n_init="auto",
            max_iter=300,
            random_state=42,
        )
        self.kmeans_model.fit(X_scaled)
        self.cluster_labels = self.kmeans_model.labels_  # 0,1,2
        # Isolation Forest (unchanged, works on scaled data)
        n_est = self.isolation_forest_estimators or 100
        self.iso_model = IsolationForest(
            n_estimators=n_est,
            contamination=self.isolation_forest_contamination,
            random_state=42,
            n_jobs=-1,
        )
        self.iso_model.fit(X_scaled)
        self.anomaly_scores = self.iso_model.decision_function(X_scaled)
        # Logging
        logger.info(
            f"Trained K‑Means – {n_clusters} clusters, "
            f"inertia={self.kmeans_model.inertia_:.2f}"
        )
        logger.info(f"Trained Isolation Forest – n_estimators={self.iso_model.n_estimators}")

    def predict(self) -> None:
        # Already computed in train_models; just ensure they exist.
        if self.cluster_labels is None or self.anomaly_scores is None:
            self.train_models()

    def save_results(self, session: Session | None = None) -> None:
        if self.segment_ids is None or self.cluster_labels is None or self.anomaly_scores is None:
            raise RuntimeError("Model not trained. Call run() or train_models() first.")
        close_after = False
        if session is None:
            session = SessionLocal()
            close_after = True
        try:
            updates = []
            for seg_id, cl, ascore in zip(self.segment_ids, self.cluster_labels, self.anomaly_scores):
                updates.append({
                    "segment_id": seg_id,
                    "cluster_id": int(cl) if cl != -1 else None,
                    "anomaly_score": float(ascore),
                })
            # Bulk update using CASE
            case_vals = ", ".join(
                f"WHEN segment_id = '{u['segment_id']}' THEN {u['cluster_id'] if u['cluster_id'] is not None else 'NULL'}"
                for u in updates
            )
            case_vals_score = ", ".join(
                f"WHEN segment_id = '{u['segment_id']}' THEN {u['anomaly_score']}"
                for u in updates
            )
            update_sql = f"""
                UPDATE activity_segment_patterns
                SET
                    cluster_id = CASE segment_id {case_vals} END,
                    anomaly_score = CASE segment_id {case_vals_score} END
                WHERE segment_id IN ({",".join(f"'{u['segment_id']}'" for u in updates)});
            """
            session.execute(update_sql)
            session.commit()
            logger.info(
                f"Updated {len(updates)} rows in activity_segment_patterns with clustering results "
                f"(model_version={self.model_version})"
            )
        except Exception:
            session.rollback()
            logger.exception("Failed to save pattern analysis results")
            raise
        finally:
            if close_after:
                session.close()

    def run(self) -> None:
        self.load_stored_features()
        self.train_models()
        self.predict()
        self.save_results()
