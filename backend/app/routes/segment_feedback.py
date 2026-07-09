"""Segment feedback routes for user correction submissions."""

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel

from app.models.db import ActivitySegmentRecord
from app.repositories.activity_segment_repository import ActivitySegmentRepository
from app.services.categorizer import categorizer

router = APIRouter(tags=["Segment Feedback"])


class SegmentLabelRequest(BaseModel):
    """Request body for segment labeling."""

    correct_label: str


@router.post("/{segment_id}/label", status_code=status.HTTP_200_OK)
async def label_segment(
    segment_id: str = Path(..., description="The ID of the segment to label"),
    request: SegmentLabelRequest = None,
):
    """
    Submit a user correction for an activity segment.

    Stores the user-provided label for supervised learning training.
    """
    if request is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is required",
        )

    # Validate the label
    valid_labels = set(categorizer.LABEL_TEXTS.keys())
    if request.correct_label not in valid_labels:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid label '{request.correct_label}'. Must be one of: {sorted(valid_labels)}",
        )

    # Get the segment from the database
    segment = ActivitySegmentRepository.get_by_id(segment_id)
    if not segment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment with ID '{segment_id}' not found",
        )

    # Store the user correction
    try:
        categorizer.store_user_correction(segment, request.correct_label)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to store segment label: {str(e)}",
        )

    return {"message": "Label correction stored successfully"}