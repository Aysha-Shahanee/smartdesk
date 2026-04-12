from app.models.browser import BrowserPayload
from app.repositories.browser_repository import BrowserRepository

class BrowserService:
    def __init__(self):
        self.repository = BrowserRepository()

    def process_and_save(self, payload: BrowserPayload):
        # TODO: Add any business logic/validation here before saving
        return self.repository.save(payload)
