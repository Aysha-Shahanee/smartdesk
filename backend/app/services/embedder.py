"""Embedding service using sentence-transformers.

Provides real embeddings for activity segments and label texts.
"""

from __future__ import annotations

import threading
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.models.db import ActivitySegmentRecord


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

        # Load model; sentence-transformers will download if not cached.
        self.model: SentenceTransformer = SentenceTransformer(self.model_name)
        # Ensure the model's output dimension matches expectation (some models may differ).
        # If mismatch, we could project or warn; for all-MiniLM-L6-v2 it's 384.
        if self.model.get_sentence_embedding_dimension() != self.dimensions:
            raise ValueError(
                f"Model {self.model_name} outputs dimension "
                f"{self.model.get_sentence_embedding_dimension()} but expected {self.dimensions}"
            )

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

        # Optionally include state and source if they provide useful context.
        # For now, we exclude them to avoid adding generic terms that may
        # dilute the semantic signal for activity classification.
        # if segment.state:
        #     text_parts.append(segment.state)
        # if segment.primary_source:
        #     text_parts.append(segment.primary_source)

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