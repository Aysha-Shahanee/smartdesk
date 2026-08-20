import hashlib
import json
import tempfile
import unittest
import math
from pathlib import Path
from unittest.mock import patch

from app.core.config import BACKEND_ROOT, settings
from app.services.github_effort_inference_service import (
    EXPECTED_FEATURE_COUNT,
    GitHubEffortInferenceService,
    ModelArtifactError,
    get_github_effort_inference_service,
    initialize_github_effort_inference,
    resolve_github_effort_artifact_dir,
)


def test_required_artifact_hashes_match_and_lightgbm_models_are_lf_only():
    artifact_dir = resolve_github_effort_artifact_dir()
    preprocessing = json.loads(
        (artifact_dir / "preprocessing_manifest.json").read_text(encoding="utf-8")
    )

    for name, expected_hash in preprocessing["required_artifacts"].items():
        content = (artifact_dir / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == expected_hash
        if name.startswith("model_"):
            assert b"\r\n" not in content


class GitHubEffortInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_github_effort_inference_service.cache_clear()
        cls.service = get_github_effort_inference_service()

    def metadata(self, **overrides):
        data = {
            "title": "Fix startup crash",
            "description": "Traceback Exception Error: failure",
            "labels": ["bug", "priority: high"],
            "repository": "microsoft/vscode",
            "started_at": "2026-08-10T10:00:00Z",
        }
        data.update(overrides)
        return data

    def assert_prediction(self, result):
        self.assertTrue(math.isfinite(result["low_hours"]))
        self.assertTrue(math.isfinite(result["typical_hours"]))
        self.assertTrue(math.isfinite(result["high_hours"]))
        self.assertGreaterEqual(result["low_hours"], 0)
        self.assertGreaterEqual(result["typical_hours"], 0)
        self.assertGreaterEqual(result["high_hours"], 0)
        self.assertEqual(result["model_version"], "github-effort-2026-08-10")

    def test_models_are_cached_and_return_real_quantiles(self):
        self.assertIs(self.service, get_github_effort_inference_service())
        self.assert_prediction(self.service.predict(self.metadata()))
        self.assertEqual(len(self.service.feature_columns), EXPECTED_FEATURE_COUNT)
        self.assertTrue(all(
            model.num_feature() == EXPECTED_FEATURE_COUNT
            for model in self.service.models.values()
        ))

    def test_internal_readiness_reports_all_three_models(self):
        readiness = initialize_github_effort_inference()
        self.assertEqual(readiness["feature_count"], 56)
        self.assertEqual(
            readiness["models_loadable"],
            {"low": True, "typical": True, "high": True},
        )
        self.assertTrue(readiness["artifacts_found"])

    def test_runtime_never_calls_lightgbm_training(self):
        with patch(
            "app.services.github_effort_inference_service.lgb.train",
            side_effect=AssertionError("runtime must not train"),
        ):
            self.assert_prediction(self.service.predict(self.metadata()))

    def test_unknown_repository_uses_missing_category_and_training_fallbacks(self):
        features = self.service.build_features(self.metadata(repository="new/example"))
        self.assertTrue(features["repository"].isna().iloc[0])
        self.assertEqual(
            features["repo_median_hours_prior"].iloc[0],
            self.service.fallbacks["global_median_hours"],
        )
        self.assert_prediction(self.service.predict(self.metadata(repository="new/example")))

    def test_unknown_empty_labels_and_missing_description_are_supported(self):
        unknown = self.service.build_features(self.metadata(labels=["never-seen-label"]))
        self.assertEqual(str(unknown["label_category"].iloc[0]), "other")
        empty = self.service.build_features(self.metadata(labels=[], description=None))
        self.assertEqual(str(empty["label_category"].iloc[0]), "unlabeled")
        self.assertEqual(empty["body_len_words"].iloc[0], 0)
        self.assert_prediction(self.service.predict(self.metadata(labels=[], description=None)))

    def test_missing_artifacts_fail_with_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ModelArtifactError, "Missing model artifact"):
                GitHubEffortInferenceService(Path(directory))


def test_default_and_explicit_artifact_path_resolution(tmp_path):
    assert resolve_github_effort_artifact_dir("", "") == (
        BACKEND_ROOT / "model_artifacts" / "github_effort"
    ).resolve()
    explicit = tmp_path / "absolute-artifacts"
    assert resolve_github_effort_artifact_dir(str(explicit), "ignored") == explicit.resolve()
    assert resolve_github_effort_artifact_dir(
        "bundled/github-effort", tmp_path
    ) == (tmp_path / "bundled" / "github-effort").resolve()


if __name__ == "__main__":
    unittest.main()
