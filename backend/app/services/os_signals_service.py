from app.models.os_signals import OSSignalPayload
from app.repositories.os_signals_repository import OSSignalsRepository

class OSSignalsService:
    def __init__(self):
        self.repository = OSSignalsRepository()

    def process_and_save(self, payload: OSSignalPayload):
        # TODO: Add any business logic/validation here before saving
        return self.repository.save(payload)
