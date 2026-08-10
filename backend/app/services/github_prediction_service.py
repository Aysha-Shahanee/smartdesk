"""Durable initial predictions for GitHub task lifecycle starts."""

import json
import logging

from sqlalchemy.orm import Session

from app.repositories.github_prediction_repository import GitHubPredictionRepository
from app.services.github_effort_inference_service import get_github_effort_inference_service
from github_data_collection.repositories import ActiveTaskRepository


logger = logging.getLogger("smartdesk.service.github_prediction")


class GitHubPredictionService:
    def __init__(self, db: Session, inference_service=None):
        self.repository = GitHubPredictionRepository(db)
        self.inference_service = inference_service

    def predict_initial(self, metadata: dict) -> None:
        row = self.repository.create_pending(metadata)
        if row.prediction_status != "pending":
            return
        try:
            predictor = self.inference_service or get_github_effort_inference_service()
            prediction = predictor.predict(metadata)
            self.repository.mark_success(row, prediction)
        except Exception as exc:
            logger.exception("Initial GitHub duration prediction failed for lifecycle %s", row.collector_lifecycle_id)
            self.repository.mark_failed(row, exc)

    def active_tasks(self, user_id: str, project_id: str | None = None) -> list[dict]:
        active = ActiveTaskRepository().list_for_user(user_id, project_id)
        predictions = self.repository.latest_for_items(
            user_id, [task["project_item_id"] for task in active]
        )
        result = []
        for task in active:
            prediction = predictions.get(task["project_item_id"])
            result.append({
                **task,
                "description": prediction.description if prediction else None,
                "labels": json.loads(prediction.labels_json or "[]") if prediction else [],
                "logical_status": "ACTIVE",
                "predicted_low_hours": prediction.predicted_low_hours if prediction else None,
                "predicted_typical_hours": prediction.predicted_typical_hours if prediction else None,
                "predicted_high_hours": prediction.predicted_high_hours if prediction else None,
                "predicted_at": prediction.predicted_at if prediction else None,
                "model_version": prediction.model_version if prediction else None,
                "prediction_status": prediction.prediction_status if prediction else "missing",
                "prediction_error": prediction.prediction_error if prediction else None,
            })
        return result
