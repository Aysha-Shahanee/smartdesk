"""Activity segment embedding repository.

Provides data-access methods for the ``activity_segment_embeddings`` table.
"""

from sqlalchemy.orm import Session

from app.models.db import ActivitySegmentEmbeddingRecord


class ActivitySegmentEmbeddingRepository:
    """Data access methods for activity segment embeddings."""

    def get_by_segment_and_model(
        self,
        db: Session,
        segment_id: str,
        model_name: str,
        model_version: str,
    ) -> ActivitySegmentEmbeddingRecord | None:
        """Get embedding for a segment by model name and version.

        Args:
            db: Database session
            segment_id: Segment identifier
            model_name: Name of the embedding model
            model_version: Version of the embedding model

        Returns:
            Embedding record if found, None otherwise
        """
        return (
            db.query(ActivitySegmentEmbeddingRecord)
            .filter(
                ActivitySegmentEmbeddingRecord.segment_id == segment_id,
                ActivitySegmentEmbeddingRecord.model_name == model_name,
                ActivitySegmentEmbeddingRecord.model_version == model_version,
            )
            .first()
        )

    def get_by_segment_id(
        self,
        db: Session,
        segment_id: str,
    ) -> list[ActivitySegmentEmbeddingRecord]:
        """Get all embeddings for a segment.

        Args:
            db: Database session
            segment_id: Segment identifier

        Returns:
            List of embedding records for the segment
        """
        return (
            db.query(ActivitySegmentEmbeddingRecord)
            .filter(ActivitySegmentEmbeddingRecord.segment_id == segment_id)
            .all()
        )

    def get_pending_embeddings(
        self,
        db: Session,
        limit: int = 100,
    ) -> list[ActivitySegmentEmbeddingRecord]:
        """Get segments whose embeddings need to be generated.

        Note: This would typically be implemented by joining with the
        activity_segments table to find segments with embedding_status
        in ('pending', 'processing') that don't have embeddings yet.

        Args:
            db: Database session
            limit: Maximum number of embeddings to return

        Returns:
            List of embedding records needing processing
        """
        # This is a simplified version - in practice, you'd join with
        # activity_segments to check embedding_status
        return (
            db.query(ActivitySegmentEmbeddingRecord)
            .limit(limit)
            .all()
        )