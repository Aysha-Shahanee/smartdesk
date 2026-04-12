from app.models.os_signals import OSSignalPayload
from app.core.database import SessionLocal
from app.models.db_models import OSSignalRecord

class OSSignalsRepository:
    def save(self, payload: OSSignalPayload):
        db = SessionLocal()
        try:
            record = OSSignalRecord(
                timestamp=payload.timestamp,
                event_type=payload.event_type,
                data=payload.data
            )
            db.add(record)
            db.commit()
            return {"status": "saved", "collection": "os_signals"}
        finally:
            db.close()
