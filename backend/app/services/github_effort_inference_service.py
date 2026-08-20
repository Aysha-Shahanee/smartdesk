"""Cached runtime inference for initial GitHub task duration estimates."""

import hashlib
import json
import pickle
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd

from app.core.config import BACKEND_ROOT, settings


EXPECTED_FEATURE_COUNT = 56
MODEL_FILES = ("model_low.txt", "model_typical.txt", "model_high.txt")
HASHED_ARTIFACTS = (
    "manifest.json",
    *MODEL_FILES,
    "tfidf_vectorizer.pkl",
    "svd_reducer.pkl",
    "inference_fallbacks.json",
    "repo_stats.json",
    "repo_label_stats.json",
    "label_categories.json",
)
REQUIRED_ARTIFACTS = ("preprocessing_manifest.json", *HASHED_ARTIFACTS)


class ModelArtifactError(RuntimeError):
    pass


def resolve_github_effort_artifact_dir(
    configured_path: str | None = None,
    resource_root: str | Path | None = None,
) -> Path:
    root_value = (
        resource_root
        if resource_root is not None
        else settings.SMARTDESK_GITHUB_RESOURCE_ROOT
    )
    root = Path(root_value).expanduser() if str(root_value).strip() else BACKEND_ROOT
    configured = (
        settings.SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR
        if configured_path is None
        else configured_path
    ).strip()
    path = Path(configured).expanduser() if configured else Path("model_artifacts/github_effort")
    if not path.is_absolute():
        path = root / path
    return path.resolve()


class GitHubEffortInferenceService:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir.resolve()
        self.preprocessing = self._json("preprocessing_manifest.json")
        self.training_manifest = self._json("manifest.json")
        self.fallbacks = self._json("inference_fallbacks.json")
        self.repo_stats = self._json("repo_stats.json")
        self.repo_label_stats = self._json("repo_label_stats.json")
        self._validate_artifacts()
        try:
            with (self.artifact_dir / "tfidf_vectorizer.pkl").open("rb") as handle:
                self.vectorizer = pickle.load(handle)
            with (self.artifact_dir / "svd_reducer.pkl").open("rb") as handle:
                self.reducer = pickle.load(handle)
        except Exception as exc:
            raise ModelArtifactError("Unable to load preprocessing artifacts") from exc
        expected = 16 + self.reducer.n_components
        feature_columns = self.training_manifest.get("feature_columns", [])
        if expected != EXPECTED_FEATURE_COUNT or len(feature_columns) != EXPECTED_FEATURE_COUNT:
            raise ModelArtifactError(
                f"Expected {EXPECTED_FEATURE_COUNT} features; artifacts are incompatible"
            )
        try:
            self.models = {
                name: lgb.Booster(model_file=str(self.artifact_dir / f"model_{name}.txt"))
                for name in ("low", "typical", "high")
            }
        except Exception as exc:
            raise ModelArtifactError("Unable to load LightGBM model artifacts") from exc
        self.feature_columns = self.training_manifest["feature_columns"]
        for name, model in self.models.items():
            if model.num_feature() != EXPECTED_FEATURE_COUNT:
                raise ModelArtifactError(
                    f"Model {name} does not have {EXPECTED_FEATURE_COUNT} features"
                )
            if model.feature_name() != self.feature_columns:
                raise ModelArtifactError(
                    f"Model {name} feature order does not match manifest.json"
                )
        categorical = self.models["typical"].pandas_categorical
        if not categorical or len(categorical) != 2:
            raise ModelArtifactError("Model categorical mappings are missing")
        self.label_categories, self.repository_categories = categorical

    def _json(self, name: str) -> Any:
        path = self.artifact_dir / name
        if not path.is_file():
            raise ModelArtifactError(f"Missing model artifact: {name}")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelArtifactError(f"Invalid model artifact: {name}") from exc

    def _validate_artifacts(self) -> None:
        if self.preprocessing.get("schema_version") != 1:
            raise ModelArtifactError("Unsupported preprocessing artifact schema")
        hashes = self.preprocessing.get("required_artifacts", {})
        if not isinstance(hashes, dict) or set(hashes) != set(HASHED_ARTIFACTS):
            raise ModelArtifactError("Preprocessing manifest has an invalid artifact set")
        for name in MODEL_FILES:
            path = self.artifact_dir / name
            if not path.is_file():
                raise ModelArtifactError(f"Missing model artifact: {name}")
            if b"\r\n" in path.read_bytes():
                raise ModelArtifactError(f"LightGBM model must use LF line endings: {name}")
        for name, expected_hash in hashes.items():
            path = self.artifact_dir / name
            if not path.is_file():
                raise ModelArtifactError(f"Missing model artifact: {name}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected_hash:
                raise ModelArtifactError(f"Model artifact checksum mismatch: {name}")

    def normalize_label(self, labels: list[str] | str | None) -> tuple[str, list[str]]:
        if isinstance(labels, str):
            tokens = [token.strip() for token in labels.split(",") if token.strip()]
        else:
            tokens = [str(token).strip() for token in (labels or []) if str(token).strip()]
        if not tokens:
            return "unlabeled", []
        for category, patterns in self.preprocessing["label_rules"].items():
            for token in tokens:
                if any(re.search(pattern, token.lower()) for pattern in patterns):
                    return category, tokens
        return "other", tokens

    def build_features(self, metadata: dict) -> pd.DataFrame:
        title = str(metadata.get("title") or "")
        description = str(metadata.get("description") or "")
        repository = str(metadata.get("repository") or "")
        label_category, labels = self.normalize_label(metadata.get("labels"))
        started = pd.to_datetime(metadata.get("started_at") or metadata.get("detected_start_time"), utc=True, errors="coerce")
        if pd.isna(started):
            started = pd.Timestamp(datetime.now(timezone.utc))

        global_median = float(self.fallbacks["global_median_hours"])
        repo_history = float(self.repo_stats.get(repository, global_median))
        repo_label_history = float(self.repo_label_stats.get(
            f"{repository}|{label_category}",
            self.fallbacks["label_median_hours"].get(label_category, global_median),
        ))
        body = description
        row = {
            "title_len_words": len(title.split()),
            "body_len_words": len(body.split()),
            "has_code_block": int(bool(re.search(r"```", body))),
            "has_stacktrace": int(bool(re.search(r"Traceback|Exception|at\s+\w+\.\w+\(|panic:|Error:", body))),
            "has_checklist": int(bool(re.search(r"- \[ \]|- \[x\]", body))),
            "has_link": int(bool(re.search(r"https?://", body))),
            "has_image": int(bool(re.search(r"!\[.*\]\(.*\)|<img", body))),
            "label_count": len(labels),
            "has_priority_label": int(bool(re.search(r"priority|urgent|critical|p0|p1", ",".join(labels).lower()))),
            "start_dayofweek": started.dayofweek,
            "start_hour_utc": started.hour,
            "days_to_weekend": max(0, 5 - started.dayofweek),
            "repo_median_hours_prior": repo_history,
            "repo_label_median_hours_prior": repo_label_history,
            "label_category": label_category,
            "repository": repository,
        }
        reduced = self.reducer.transform(self.vectorizer.transform([(title + " " + description).lower()]))[0]
        row.update({f"text_svd_{index}": float(value) for index, value in enumerate(reduced)})
        frame = pd.DataFrame([row], columns=self.feature_columns)
        frame["label_category"] = pd.Categorical(frame["label_category"], categories=self.label_categories)
        if repository not in self.repository_categories:
            frame.loc[0, "repository"] = None
        frame["repository"] = pd.Categorical(frame["repository"], categories=self.repository_categories)
        return frame

    def predict(self, metadata: dict) -> dict:
        features = self.build_features(metadata)
        values = {
            name: max(0.0, float(np.expm1(model.predict(features)[0])))
            for name, model in self.models.items()
        }
        return {
            "low_hours": values["low"],
            "typical_hours": values["typical"],
            "high_hours": values["high"],
            "model_version": self.preprocessing["model_version"],
        }

    def readiness(self) -> dict[str, object]:
        return {
            "ready": True,
            "artifacts_found": all(
                (self.artifact_dir / name).is_file() for name in REQUIRED_ARTIFACTS
            ),
            "manifests_valid": True,
            "models_loadable": {name: True for name in ("low", "typical", "high")},
            "feature_count": len(self.feature_columns),
            "model_version": self.preprocessing["model_version"],
        }


@lru_cache(maxsize=1)
def get_github_effort_inference_service() -> GitHubEffortInferenceService:
    return GitHubEffortInferenceService(resolve_github_effort_artifact_dir())


def initialize_github_effort_inference() -> dict[str, object]:
    """Load and validate the cached runtime artifacts; never trains models."""
    return get_github_effort_inference_service().readiness()
