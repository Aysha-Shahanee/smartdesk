"""Durable initial predictions for GitHub task lifecycle starts."""

import json
import logging

from sqlalchemy.orm import Session

from app.repositories.github_prediction_repository import GitHubPredictionRepository
from app.services.github_effort_inference_service import get_github_effort_inference_service
from github_data_collection.repositories import ActiveTaskRepository
from app.services.github_task_time_spent_service import GitHubTaskTimeSpentService
from app.services.github_remaining_time_service import GitHubRemainingTimeService


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
        active_repository = ActiveTaskRepository()
        active = active_repository.list_for_user(user_id, project_id)
        # Attribution must consider every lifecycle for this SmartDesk user,
        # not only the selected Project's visible cards. Otherwise a second
        # active lifecycle in another Project could receive the same time.
        attribution_active = (
            active_repository.list_for_user(user_id, None) if project_id else active
        )
        predictions = self.repository.for_open_lifecycles(
            user_id, [task["collector_lifecycle_id"] for task in active]
        )
        time_service = GitHubTaskTimeSpentService(self.repository.db)
        active_for_time = [
            {**candidate, "user_id": user_id} for candidate in attribution_active
        ]
        result = []
        for task in active:
            prediction = predictions.get(task["collector_lifecycle_id"])
            lifecycle_for_time = {**task, "user_id": user_id}
            time_spent = time_service.calculate(lifecycle_for_time, active_for_time).to_dict()
            predicted_typical_hours = (
                prediction.predicted_typical_hours if prediction else None
            )
            remaining_time = GitHubRemainingTimeService.calculate(
                predicted_typical_hours,
                time_spent,
                lifecycle_status=task.get("logical_status", "ACTIVE"),
            ).to_dict()
            result.append({
                **task,
                **time_spent,
                **remaining_time,
                "description": prediction.description if prediction else None,
                "labels": json.loads(prediction.labels_json or "[]") if prediction else [],
                "logical_status": "ACTIVE",
                "predicted_low_hours": prediction.predicted_low_hours if prediction else None,
                "predicted_typical_hours": predicted_typical_hours,
                "predicted_high_hours": prediction.predicted_high_hours if prediction else None,
                "predicted_at": prediction.predicted_at if prediction else None,
                "model_version": prediction.model_version if prediction else None,
                "prediction_status": prediction.prediction_status if prediction else "missing",
                "prediction_error": prediction.prediction_error if prediction else None,
            })
        return result
