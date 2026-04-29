from app.models.calendar_event import CalendarEventPayload
from app.repositories.calendar_event_repository import CalendarEventRepository


class CalendarEventService:
    def __init__(self):
        self.repository = CalendarEventRepository()

    def process_and_save(self, payload: CalendarEventPayload):
        return self.repository.upsert(payload)

    def list(self, user_id: str | None = None, start_time: str | None = None, end_time: str | None = None, limit: int = 200):
        return self.repository.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)
