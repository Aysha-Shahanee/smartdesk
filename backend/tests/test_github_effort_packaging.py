import math
import shutil

import pytest

from app.core.config import settings
from app.services.github_effort_inference_service import (
    REQUIRED_ARTIFACTS,
    ModelArtifactError,
    get_github_effort_inference_service,
    resolve_github_effort_artifact_dir,
)


def copy_runtime_artifacts(destination):
    destination.mkdir(parents=True)
    source = resolve_github_effort_artifact_dir()
    for name in REQUIRED_ARTIFACTS:
        shutil.copy2(source / name, destination / name)


@pytest.fixture
def packaged_artifacts(tmp_path):
    destination = tmp_path / "application-resources" / "backend" / "model_artifacts" / "github_effort"
    copy_runtime_artifacts(destination)
    return destination


def test_copied_runtime_artifacts_load_and_predict_without_repository_cwd(
    packaged_artifacts, tmp_path, monkeypatch
):
    unrelated_cwd = tmp_path / "installed-application-working-directory"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setattr(
        settings, "SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR", str(packaged_artifacts)
    )
    get_github_effort_inference_service.cache_clear()
    try:
        service = get_github_effort_inference_service()
        assert service.artifact_dir == packaged_artifacts.resolve()
        assert {path.name for path in packaged_artifacts.iterdir()} == set(REQUIRED_ARTIFACTS)
        result = service.predict({
            "title": "Package the local prediction runtime",
            "description": "Verify inference without source or training data",
            "labels": ["feature"],
            "repository": "microsoft/vscode",
            "started_at": "2026-08-20T10:00:00Z",
        })
        assert all(
            math.isfinite(result[key]) and result[key] >= 0
            for key in ("low_hours", "typical_hours", "high_hours")
        )
    finally:
        get_github_effort_inference_service.cache_clear()


@pytest.mark.parametrize("missing_name", REQUIRED_ARTIFACTS)
def test_packaged_runtime_rejects_each_missing_required_artifact(
    packaged_artifacts, missing_name
):
    (packaged_artifacts / missing_name).unlink()
    with pytest.raises(ModelArtifactError, match="Missing model artifact"):
        from app.services.github_effort_inference_service import GitHubEffortInferenceService

        GitHubEffortInferenceService(packaged_artifacts)

