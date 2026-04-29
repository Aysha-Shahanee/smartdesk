from app.models.os_minute_window import OSMinuteWindowPayload
from app.repositories.os_minute_window_repository import OSMinuteWindowRepository


class OSMinuteWindowService:
    def __init__(self):
        self.repository = OSMinuteWindowRepository()

    def process_and_save(self, payload: OSMinuteWindowPayload):
        return self.repository.upsert(payload)

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 100):
        return self.repository.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)
