import tempfile
import unittest
from pathlib import Path

from app.core.config import settings
from app.services.github_effort_inference_service import (
    GitHubEffortInferenceService,
    ModelArtifactError,
    get_github_effort_inference_service,
)


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
        self.assertGreaterEqual(result["low_hours"], 0)
        self.assertGreaterEqual(result["typical_hours"], 0)
        self.assertGreaterEqual(result["high_hours"], 0)
        self.assertEqual(result["model_version"], "github-effort-2026-08-10")

    def test_models_are_cached_and_return_real_quantiles(self):
        self.assertIs(self.service, get_github_effort_inference_service())
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


if __name__ == "__main__":
    unittest.main()
