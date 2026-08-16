"""Embedding service using sentence-transformers.

Provides real embeddings for activity segments and label texts.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.models.db import ActivitySegmentRecord

logger = logging.getLogger("smartdesk.embedder")


class Embedder:
    """Singleton service for generating embeddings using SentenceTransformer."""

    _instance_lock = threading.Lock()
    _instance: Optional["Embedder"] = None

    def __new__(cls) -> "Embedder":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Load the SentenceTransformer model based on settings."""
        self.model_name: str = settings.EMBEDDING_MODEL
        self.model_version: str = settings.EMBEDDING_VERSION
        self.dimensions: int = settings.EMBEDDING_DIM
        self.model_source: str = "hub"

        self.model: SentenceTransformer = self._load_model()

        # Ensure the model's output dimension matches expectation (some models
        # may differ). For all-MiniLM-L6-v2 it's 384.
        actual = self._embedding_dimension()
        if actual != self.dimensions:
            raise ValueError(
                f"Model {self.model_name} outputs dimension "
                f"{actual} but expected {self.dimensions}"
            )

    def _load_model(self) -> SentenceTransformer:
        """Load the encoder, preferring a bundled copy over a hub download.

        Plain ``SentenceTransformer(name)`` reaches out to huggingface.co on
        every cold start: ~88 MB on a machine with no cache, and an outright
        failure with no network. That is fine on a dev box and wrong for a
        packaged desktop app, so a local directory wins when one is
        configured.

        ``EMBEDDING_MODEL_PATH`` points at an unpacked model directory (the
        one containing ``config.json`` / ``modules.json``); ship that with the
        app. Otherwise the hub copy is used but pinned to
        ``EMBEDDING_CACHE_DIR`` when set, so the download lands somewhere you
        control and can bundle later.
        """
        local_path = (settings.EMBEDDING_MODEL_PATH or "").strip()
        if local_path:
            path = Path(local_path).expanduser()
            if path.is_dir():
                logger.info("loading embedding model from %s", path)
                self.model_source = "local"
                return SentenceTransformer(str(path), local_files_only=True)
            logger.warning(
                "EMBEDDING_MODEL_PATH=%s is not a directory; falling back to "
                "the hub, which needs network access on first run.", path,
            )

        cache_dir = (settings.EMBEDDING_CACHE_DIR or "").strip() or None
        if cache_dir:
            Path(cache_dir).expanduser().mkdir(parents=True, exist_ok=True)
        logger.info(
            "loading embedding model %s from the hub%s",
            self.model_name, f" (cache: {cache_dir})" if cache_dir else "",
        )
        return SentenceTransformer(self.model_name, cache_folder=cache_dir)

    def _embedding_dimension(self) -> int:
        """Output dimension, across sentence-transformers versions.

        ``get_sentence_embedding_dimension`` was renamed to
        ``get_embedding_dimension`` in 5.x and now emits a FutureWarning on
        every startup; prefer the new name when it exists.
        """
        getter = getattr(self.model, "get_embedding_dimension", None)
        if callable(getter):
            return getter()
        return self.model.get_sentence_embedding_dimension()

    def generate_embedding(self, text: str) -> List[float]:
        """Return a normalized embedding vector for the given text.

        Args:
            text: Input text to embed.

        Returns:
            List of floats (unit-norm embedding).
        """
        # SentenceTransformer returns a numpy array; ensure float32 for consistency.
        embedding: np.ndarray = self.model.encode(
            text, convert_to_numpy=True, normalize_embeddings=True
        )
        # normalize_embeddings already returns unit norm, but we cast to list.
        return embedding.tolist()

    def embed_segment(
        self,
        segment: ActivitySegmentRecord,
    ) -> Optional[List[float]]:
        """Create an embedding for an activity segment.

        Combines available text fields from the segment to create a meaningful
        representation for embedding.

        Args:
            segment: Activity segment to embed.

        Returns:
            Embedding vector as list of floats, or None if no text content.
        """
        # Collect text content from available fields
        text_parts: List[str] = []
        if segment.app_name:
            text_parts.append(segment.app_name)
        if segment.title:
            text_parts.append(segment.title)
        if segment.detail:
            text_parts.append(segment.detail)

        # segment.state and segment.primary_source are deliberately excluded:
        # they contribute generic terms that dilute the semantic signal for
        # activity classification.

        if not text_parts:
            return None

        # Join all text parts with spaces to form a natural language-like string.
        combined_text: str = " ".join(text_parts)

        # Generate and return embedding
        return self.generate_embedding(combined_text)

    def compute_similarity(
        self,
        embedding1: List[float],
        embedding2: List[float],
    ) -> float:
        """Compute cosine similarity between two embedding vectors.

        Since embeddings are already unit‑norm, dot product equals cosine similarity.

        Args:
            embedding1: First vector.
            embedding2: Second vector.

        Returns:
            Cosine similarity between -1 and 1 (typically 0‑1 for unit vectors).
        """
        if len(embedding1) != len(embedding2):
            raise ValueError("Embedding vectors must have the same dimension")
        # Using numpy for efficiency and numerical stability.
        return float(np.dot(embedding1, embedding2))


# Provide a module‑level singleton for convenience.
embedder = Embedder()