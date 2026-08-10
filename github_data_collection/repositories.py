"""Storage interfaces used by the live collection services.

Only this module knows about SQLAlchemy.  A future backend can replace these
classes with Postgres-backed implementations without changing webhook logic.
"""

from datetime import datetime, timezone
from typing import Dict, Optional

from .database import (
    ActiveTask,
    CollectedTask,
    ProjectItemState,
    ProjectStatusMapping,
    SessionLocal,
    WebhookDelivery,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CollectedTaskRepository:
    def __init__(self, session_factory=SessionLocal):
        self.session_factory = session_factory

    def insert(self, metadata: Dict) -> int:
        values = self._mutable_values(metadata)
        started_at = metadata.get("started_at") or metadata.get("detected_start_time") or utc_now()
        values.update(
            detected_start_time=started_at,
            started_at=started_at,
            completed_at=None,
        )
        with self.session_factory() as session:
            row = CollectedTask(**values)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def update_latest(self, project_item_id: str, metadata: Dict) -> int:
        """Refresh mutable fields without changing lifecycle timestamps."""
        with self.session_factory() as session:
            row = (
                session.query(CollectedTask)
                .filter(CollectedTask.project_item_id == project_item_id)
                .order_by(CollectedTask.id.desc())
                .first()
            )
            if row is None:
                started_at = metadata.get("started_at") or metadata.get("detected_start_time") or utc_now()
                row = CollectedTask(
                    **self._mutable_values(metadata),
                    detected_start_time=started_at,
                    started_at=started_at,
                )
                session.add(row)
            else:
                for key, value in self._mutable_values(metadata).items():
                    setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return row.id

    def complete_latest(self, project_item_id: str, metadata: Dict,
                        completed_at: Optional[str] = None) -> None:
        """Complete the latest lifecycle while preserving its original start."""
        with self.session_factory() as session:
            row = (
                session.query(CollectedTask)
                .filter(CollectedTask.project_item_id == project_item_id)
                .order_by(CollectedTask.id.desc())
                .first()
            )
            if row is None:
                started_at = metadata.get("started_at") or metadata.get("detected_start_time") or utc_now()
                row = CollectedTask(
                    **self._mutable_values(metadata),
                    detected_start_time=started_at,
                    started_at=started_at,
                )
                session.add(row)
            else:
                for key, value in self._mutable_values(metadata).items():
                    setattr(row, key, value)
            row.completed_at = completed_at or utc_now()
            session.commit()

    @staticmethod
    def _mutable_values(metadata: Dict) -> Dict:
        import json

        return {
            "project_item_id": metadata.get("project_item_id"),
            "issue_id": metadata.get("issue_id"),
            "title": metadata.get("title"),
            "description": metadata.get("description"),
            "status": metadata.get("status"),
            "priority": metadata.get("priority"),
            "labels": json.dumps(metadata.get("labels") or []),
            "assignees": json.dumps(metadata.get("assignees") or []),
            "comments_count": metadata.get("comments_count"),
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "smartdesk_user_id": metadata.get("smartdesk_user_id"),
            "project_id": metadata.get("project_id"),
            "repository": metadata.get("repository"),
        }


class ActiveTaskRepository:
    def add(self, metadata: Dict) -> None:
        with SessionLocal() as session:
            project_item_id = metadata["project_item_id"]
            row = session.get(ActiveTask, project_item_id)
            if row is None:
                session.add(ActiveTask(
                    project_item_id=project_item_id,
                    issue_id=metadata["issue_id"],
                    title=metadata.get("title") or "",
                    started_at=metadata["detected_start_time"],
                    smartdesk_user_id=metadata.get("smartdesk_user_id"),
                    project_id=metadata.get("project_id"),
                    repository=metadata.get("repository"),
                ))
            else:
                row.smartdesk_user_id = metadata.get("smartdesk_user_id") or row.smartdesk_user_id
                row.project_id = metadata.get("project_id") or row.project_id
                row.repository = metadata.get("repository") or row.repository
            session.commit()

    def list_for_user(self, smartdesk_user_id: str, project_id: Optional[str] = None) -> list[Dict]:
        with SessionLocal() as session:
            query = session.query(ActiveTask).filter(ActiveTask.smartdesk_user_id == smartdesk_user_id)
            if project_id:
                query = query.filter(ActiveTask.project_id == project_id)
            return [
                {
                    "project_item_id": row.project_item_id,
                    "issue_id": row.issue_id,
                    "title": row.title,
                    "started_at": row.started_at,
                    "project_id": row.project_id,
                    "repository": row.repository,
                }
                for row in query.all()
            ]

    def remove(self, project_item_id: str) -> None:
        with SessionLocal() as session:
            row = session.get(ActiveTask, project_item_id)
            if row is not None:
                session.delete(row)
                session.commit()


class ProjectItemStateRepository:
    def get(self, project_item_id: str) -> Optional[Dict]:
        with SessionLocal() as session:
            row = session.get(ProjectItemState, project_item_id)
            if row is None:
                return None
            return {
                "project_item_id": row.project_item_id,
                "project_id": row.project_id,
                "status_option_name": row.status_option_name,
                "logical_status": row.logical_status,
                "updated_at": row.updated_at,
            }

    def upsert(self, project_item_id: str, project_id: str,
               status_option_name: Optional[str], logical_status: str) -> None:
        with SessionLocal() as session:
            row = session.get(ProjectItemState, project_item_id)
            if row is None:
                row = ProjectItemState(project_item_id=project_item_id)
                session.add(row)
            row.project_id = project_id
            row.status_option_name = status_option_name
            row.logical_status = logical_status
            row.updated_at = utc_now()
            session.commit()


class StatusMappingRepository:
    def replace(self, project_id: str, mapping: Dict[str, str]) -> None:
        with SessionLocal() as session:
            session.query(ProjectStatusMapping).filter(
                ProjectStatusMapping.project_id == project_id
            ).delete()
            for option_name, logical_status in mapping.items():
                session.add(ProjectStatusMapping(
                    project_id=project_id,
                    status_option_name=option_name,
                    logical_status=logical_status,
                ))
            session.commit()

    def get_logical(self, project_id: str, option_name: Optional[str]) -> str:
        if not option_name:
            return "OTHER"
        with SessionLocal() as session:
            rows = session.query(ProjectStatusMapping).filter(
                ProjectStatusMapping.project_id == project_id
            ).all()
            wanted = option_name.strip().casefold()
            for row in rows:
                if row.status_option_name.strip().casefold() == wanted:
                    return row.logical_status
        return "OTHER"


class WebhookDeliveryRepository:
    def is_processed(self, delivery_id: Optional[str]) -> bool:
        if not delivery_id:
            return False
        with SessionLocal() as session:
            return session.get(WebhookDelivery, delivery_id) is not None

    def mark_processed(self, delivery_id: Optional[str]) -> None:
        if not delivery_id:
            return
        with SessionLocal() as session:
            if session.get(WebhookDelivery, delivery_id) is None:
                session.add(WebhookDelivery(delivery_id=delivery_id, processed_at=utc_now()))
                session.commit()
