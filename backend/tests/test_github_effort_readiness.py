import hashlib
import asyncio
import json
from pathlib import Path
import shutil

import pytest

from app.services.github_effort_inference_service import (
    GitHubEffortInferenceService,
    ModelArtifactError,
    resolve_github_effort_artifact_dir,
)


@pytest.fixture
def copied_artifacts(tmp_path):
    destination = tmp_path / "github_effort"
    shutil.copytree(resolve_github_effort_artifact_dir(), destination)
    return destination


def test_hash_mismatch_is_rejected(copied_artifacts):
    path = copied_artifacts / "repo_stats.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ModelArtifactError, match="checksum mismatch: repo_stats.json"):
        GitHubEffortInferenceService(copied_artifacts)


def test_crlf_model_is_rejected_even_if_manifest_hash_matches(copied_artifacts):
    model_path = copied_artifacts / "model_low.txt"
    model_path.write_bytes(model_path.read_bytes().replace(b"\n", b"\r\n"))
    preprocessing_path = copied_artifacts / "preprocessing_manifest.json"
    preprocessing = json.loads(preprocessing_path.read_text(encoding="utf-8"))
    preprocessing["required_artifacts"]["model_low.txt"] = hashlib.sha256(
        model_path.read_bytes()
    ).hexdigest()
    preprocessing_path.write_text(json.dumps(preprocessing), encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="must use LF line endings"):
        GitHubEffortInferenceService(copied_artifacts)


def test_wrong_feature_count_is_rejected(copied_artifacts):
    manifest_path = copied_artifacts / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["feature_columns"].pop()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    preprocessing_path = copied_artifacts / "preprocessing_manifest.json"
    preprocessing = json.loads(preprocessing_path.read_text(encoding="utf-8"))
    preprocessing["required_artifacts"]["manifest.json"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    preprocessing_path.write_text(json.dumps(preprocessing), encoding="utf-8")
    with pytest.raises(ModelArtifactError, match="Expected 56 features"):
        GitHubEffortInferenceService(copied_artifacts)


def test_missing_hashed_runtime_artifact_is_rejected(copied_artifacts):
    (copied_artifacts / "inference_fallbacks.json").unlink()
    with pytest.raises(ModelArtifactError, match="Missing model artifact"):
        GitHubEffortInferenceService(copied_artifacts)


def test_backend_records_readiness_failure_without_aborting_unrelated_startup(monkeypatch):
    import app.main as backend_main

    class NoOpJob:
        def start(self):
            pass

        def stop(self):
            pass

    class DummySession:
        def rollback(self):
            pass

        def close(self):
            pass

    for name in (
        "_timeout_job", "_work_scheduler", "_os_collector", "_calendar_sync_job",
        "_activity_segment_builder", "_recommendation_job",
    ):
        monkeypatch.setattr(backend_main, name, NoOpJob())
    monkeypatch.setattr(backend_main, "SessionLocal", DummySession)
    monkeypatch.setattr(backend_main, "get_last_heartbeat", lambda *_: None)
    monkeypatch.setattr(backend_main, "reconcile_open_sessions", lambda *_: None)
    monkeypatch.setattr(
        backend_main.emotion, "stop_emotion_service_if_running", lambda: None
    )
    monkeypatch.setattr(
        backend_main,
        "initialize_github_effort_inference",
        lambda: (_ for _ in ()).throw(ModelArtifactError("Missing model artifact: model_low.txt")),
    )

    async def exercise():
        async with backend_main.lifespan(backend_main.app):
            assert backend_main.app.state.github_effort_readiness == {
                "ready": False,
                "error": "Missing model artifact: model_low.txt",
            }

    asyncio.run(exercise())
