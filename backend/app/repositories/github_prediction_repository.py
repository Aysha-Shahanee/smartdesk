import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.db_models import GitHubInitialPredictionRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GitHubPredictionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_lifecycle(self, lifecycle_id: int):
        return self.db.query(GitHubInitialPredictionRecord).filter_by(
            collector_lifecycle_id=lifecycle_id
        ).first()

    def create_pending(self, metadata: dict) -> GitHubInitialPredictionRecord:
        existing = self.get_by_lifecycle(metadata["collector_lifecycle_id"])
        if existing:
            return existing
        row = GitHubInitialPredictionRecord(
            collector_lifecycle_id=metadata["collector_lifecycle_id"],
            user_id=metadata["smartdesk_user_id"],
            project_id=metadata["project_id"],
            project_item_id=metadata["project_item_id"],
            issue_id=metadata["issue_id"],
            title=metadata.get("title"),
            description=metadata.get("description"),
            labels_json=json.dumps(metadata.get("labels") or []),
            repository=metadata.get("repository"),
            started_at=metadata.get("started_at") or metadata["detected_start_time"],
            predicted_at=utc_now(),
            prediction_status="pending",
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def mark_success(self, row, prediction: dict) -> None:
        row.predicted_low_hours = prediction["low_hours"]
        row.predicted_typical_hours = prediction["typical_hours"]
        row.predicted_high_hours = prediction["high_hours"]
        row.model_version = prediction["model_version"]
        row.prediction_status = "succeeded"
        row.prediction_error = None
        self.db.commit()

    def mark_failed(self, row, exc: Exception) -> None:
        row.prediction_status = "failed"
        row.prediction_error = str(exc)[:1000]
        self.db.commit()

    def for_open_lifecycles(self, user_id: str, lifecycle_ids: list[int]) -> dict:
        if not lifecycle_ids:
            return {}
        rows = (
            self.db.query(GitHubInitialPredictionRecord)
            .filter(
                GitHubInitialPredictionRecord.user_id == user_id,
                GitHubInitialPredictionRecord.collector_lifecycle_id.in_(lifecycle_ids),
            )
            .all()
        )
        return {row.collector_lifecycle_id: row for row in rows}
