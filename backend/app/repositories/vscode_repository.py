from app.models.vscode import VSCodePayload
from app.core.database import SessionLocal
from app.models.db_models import VSCodeRecord

class VSCodeRepository:
    def save(self, payload: VSCodePayload):
        db = SessionLocal()
        try:
            record = VSCodeRecord(
                timestamp=payload.timestamp,
                event_type=payload.event_type,
                data=payload.data
            )
            db.add(record)
            db.commit()
            return {"status": "saved", "collection": "vscode"}
        finally:
            db.close()
