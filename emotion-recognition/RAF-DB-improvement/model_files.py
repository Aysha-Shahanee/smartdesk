from __future__ import annotations

import urllib.request
from pathlib import Path


RAF_MODEL_FILENAME = "emotion_model_raf.pth"
RAF_MODEL_URL = (
    "https://huggingface.co/AD-Nawarathna/Emotion_Detection_FER_2013"
    "/resolve/main/emotion_model_raf.pth"
)


def ensure_raf_model_file(project_dir: Path) -> Path:
    models_dir = Path(project_dir) / "models"
    model_path = models_dir / RAF_MODEL_FILENAME

    if model_path.exists() and model_path.stat().st_size > 0:
        print(f"Using existing model file: {model_path}")
        return model_path

    models_dir.mkdir(parents=True, exist_ok=True)
    temp_path = model_path.with_suffix(model_path.suffix + ".download")
    if temp_path.exists():
        temp_path.unlink()

    print(f"Downloading model file: {RAF_MODEL_FILENAME}")
    print(f"Source: {RAF_MODEL_URL}")
    print(f"Destination: {model_path}")

    try:
        _download_file(RAF_MODEL_URL, temp_path)
        temp_path.replace(model_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise

    print(f"Model download complete: {model_path}")
    return model_path


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
