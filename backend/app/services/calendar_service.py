from app.models.calendar import CalendarPayload
from app.repositories.calendar_repository import CalendarRepository


class CalendarService:
    def __init__(self):
        self.repository = CalendarRepository()

    def process_and_save(self, payload: CalendarPayload):
        # Placeholder for any future business logic/validation
        return self.repository.save(payload)
