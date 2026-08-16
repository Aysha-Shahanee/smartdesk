from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path


RAF_MODEL_FILENAME = "emotion_model_raf.pth"
RAF_MODEL_URL = (
    "https://huggingface.co/AD-Nawarathna/Emotion_Detection_FER_2013"
    "/resolve/main/emotion_model_raf.pth"
)

# The checkpoint is loaded straight into torch, so an unverified download is a
# supply-chain hole: whatever the URL serves becomes code the app trusts. Pin
# the artifact we validated and refuse anything else, the same way the GitHub
# effort model is pinned in backend/model_artifacts/.../preprocessing_manifest.json.
RAF_MODEL_SHA256 = "bd87c6ebb52728fd0598cf944f0ca72c10469e918b19410e8966c64a220abd79"
RAF_MODEL_BYTES = 6224155


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_raf_model_file(project_dir: Path) -> Path:
    models_dir = Path(project_dir) / "models"
    model_path = models_dir / RAF_MODEL_FILENAME

    if model_path.exists() and model_path.stat().st_size > 0:
        actual = file_sha256(model_path)
        if actual == RAF_MODEL_SHA256:
            print(f"Using existing model file: {model_path}")
            return model_path
        # A corrupt or swapped cache is recoverable — discard and re-fetch once.
        print(f"Cached model file failed verification, re-downloading: {model_path}")
        model_path.unlink()

    models_dir.mkdir(parents=True, exist_ok=True)
    temp_path = model_path.with_suffix(model_path.suffix + ".download")
    if temp_path.exists():
        temp_path.unlink()

    print(f"Downloading model file: {RAF_MODEL_FILENAME}")
    print(f"Source: {RAF_MODEL_URL}")
    print(f"Destination: {model_path}")

    try:
        _download_file(RAF_MODEL_URL, temp_path)
        _verify_download(temp_path)
        temp_path.replace(model_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    print(f"Model download complete: {model_path}")
    return model_path


def _verify_download(path: Path) -> None:
    actual_size = path.stat().st_size
    if actual_size != RAF_MODEL_BYTES:
        raise RuntimeError(
            f"Downloaded model is {actual_size} bytes, expected {RAF_MODEL_BYTES}. "
            f"Refusing to load it."
        )

    actual_hash = file_sha256(path)
    if actual_hash != RAF_MODEL_SHA256:
        raise RuntimeError(
            f"Downloaded model failed SHA-256 verification.\n"
            f"  expected: {RAF_MODEL_SHA256}\n"
            f"  actual:   {actual_hash}\n"
            f"Refusing to load it."
        )


def _download_file(url: str, destination: Path) -> None:
    with urllib.request.urlopen(url) as response:
        total_size = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        next_progress = 10

        with destination.open("wb") as file:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break

                file.write(chunk)
                downloaded += len(chunk)

                if total_size:
                    progress = int(downloaded * 100 / total_size)
                    if progress >= next_progress:
                        print(f"Download progress: {progress}%")
                        next_progress += 10

    if destination.stat().st_size == 0:
        raise RuntimeError("Downloaded model file is empty.")
