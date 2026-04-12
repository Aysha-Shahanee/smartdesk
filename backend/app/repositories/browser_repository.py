from app.models.browser import BrowserPayload
from app.core.database import SessionLocal
from app.models.db_models import BrowserRecord

class BrowserRepository:
    def save(self, payload: BrowserPayload):
        db = SessionLocal()
        try:
            record = BrowserRecord(
                timestamp=payload.timestamp,
                event_type=payload.event_type,
                data=payload.data
            )
            db.add(record)
            db.commit()
            return {"status": "saved", "collection": "browser"}
        finally:
            db.close()
