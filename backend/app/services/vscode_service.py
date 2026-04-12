from app.models.vscode import VSCodePayload
from app.repositories.vscode_repository import VSCodeRepository

class VSCodeService:
    def __init__(self):
        self.repository = VSCodeRepository()

    def process_and_save(self, payload: VSCodePayload):
        # TODO: Add any business logic/validation here before saving
        return self.repository.save(payload)
