from sqlalchemy.orm import Session

from app.models.vscode_minute_window import VSCodeMinuteWindowPayload
from app.repositories.vscode_minute_window_repository import VSCodeMinuteWindowRepository


class VSCodeMinuteWindowService:
    def __init__(self, db: Session | None = None):
        self.repository = VSCodeMinuteWindowRepository(db)

    def process_and_save(self, payload: VSCodeMinuteWindowPayload):
        return self.repository.upsert(payload)
