from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.db_models import GitHubConnectionRecord, GitHubOAuthStateRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class GitHubIntegrationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_connection(self, user_id: str) -> Optional[GitHubConnectionRecord]:
        return self.db.query(GitHubConnectionRecord).filter_by(user_id=user_id).first()

    def get_connection_by_project(self, project_id: str) -> Optional[GitHubConnectionRecord]:
        return self.db.query(GitHubConnectionRecord).filter_by(selected_project_id=project_id).first()

    def connect(self, user_id: str, github_login: str,
                installation_id: int) -> GitHubConnectionRecord:
        row = self.get_connection(user_id)
        now = utc_now()
        if row is None:
            row = GitHubConnectionRecord(user_id=user_id, created_at=now)
            self.db.add(row)
        row.github_login = github_login
        row.installation_id = installation_id
        row.connection_status = "connected"
        row.updated_at = now
        self.db.commit()
        self.db.refresh(row)
        return row

    def select_project(self, user_id: str, owner: str, project_number: int,
                       project_id: str, title: Optional[str]) -> GitHubConnectionRecord:
        row = self.get_connection(user_id)
        if row is None:
            raise LookupError("GitHub is not connected")
        row.selected_owner = owner
        row.selected_project_number = project_number
        row.selected_project_id = project_id
        row.selected_project_title = title
        row.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(row)
        return row

    def disconnect(self, user_id: str) -> None:
        row = self.get_connection(user_id)
        if row:
            row.connection_status = "disconnected"
            row.updated_at = utc_now()
            self.db.commit()

    def create_state(self, user_id: str, state_hash: str, lifetime_minutes: int = 10) -> None:
        now = datetime.now(timezone.utc)
        self.db.add(GitHubOAuthStateRecord(
            state_hash=state_hash,
            user_id=user_id,
            created_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=lifetime_minutes)).isoformat().replace("+00:00", "Z"),
        ))
        self.db.commit()

    def consume_state(self, state_hash: str) -> str:
        row = self.db.query(GitHubOAuthStateRecord).filter_by(state_hash=state_hash).first()
        now = datetime.now(timezone.utc)
        if row is None or row.used_at or datetime.fromisoformat(row.expires_at.replace("Z", "+00:00")) < now:
            raise ValueError("Invalid or expired OAuth state")
        row.used_at = now.isoformat().replace("+00:00", "Z")
        self.db.commit()
        return row.user_id
