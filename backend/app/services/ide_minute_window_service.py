from sqlalchemy.orm import Session

from app.models.ide_minute_window import IDEMinuteWindowPayload
from app.repositories.ide_minute_window_repository import IDEMinuteWindowRepository


class IDEMinuteWindowService:
    def __init__(self, db: Session | None = None):
        self.repository = IDEMinuteWindowRepository(db)

    def process_and_save(self, payload: IDEMinuteWindowPayload):
        return self.repository.upsert(payload)
