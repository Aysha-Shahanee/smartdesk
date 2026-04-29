from sqlalchemy.orm import Session

from app.models.browser_minute_window import BrowserMinuteWindowPayload
from app.repositories.browser_minute_window_repository import BrowserMinuteWindowRepository


class BrowserMinuteWindowService:
    def __init__(self, db: Session | None = None):
        self.repository = BrowserMinuteWindowRepository(db)

    def process_and_save(self, payload: BrowserMinuteWindowPayload):
        return self.repository.upsert(payload)
