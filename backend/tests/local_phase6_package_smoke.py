"""Copy only runtime artifacts and perform real inference outside the repo cwd."""

import math
import os
from pathlib import Path
import shutil
import tempfile

from app.core.config import settings
from app.services.github_effort_inference_service import (
    REQUIRED_ARTIFACTS,
    get_github_effort_inference_service,
    resolve_github_effort_artifact_dir,
)


def main() -> None:
    source = resolve_github_effort_artifact_dir()
    original_cwd = Path.cwd()
    original_config = settings.SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        packaged = root / "application-resources" / "backend" / "model_artifacts" / "github_effort"
        packaged.mkdir(parents=True)
        for name in REQUIRED_ARTIFACTS:
            shutil.copy2(source / name, packaged / name)
        isolated_cwd = root / "installed-working-directory"
        isolated_cwd.mkdir()
        try:
            os.chdir(isolated_cwd)
            settings.SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR = str(packaged)
            get_github_effort_inference_service.cache_clear()
            service = get_github_effort_inference_service()
            prediction = service.predict({
                "title": "Verify packaged resources",
                "description": "No training dataset or repository path is available",
                "labels": ["chore"],
                "repository": "microsoft/vscode",
                "started_at": "2026-08-20T10:00:00Z",
            })
            assert service.artifact_dir == packaged.resolve()
            assert set(path.name for path in packaged.iterdir()) == set(REQUIRED_ARTIFACTS)
            assert all(
                math.isfinite(prediction[key]) and prediction[key] >= 0
                for key in ("low_hours", "typical_hours", "high_hours")
            )
            print("Local Phase 6 package-copy inference smoke test passed")
        finally:
            get_github_effort_inference_service.cache_clear()
            settings.SMARTDESK_GITHUB_MODEL_ARTIFACT_DIR = original_config
            os.chdir(original_cwd)


if __name__ == "__main__":
    main()
