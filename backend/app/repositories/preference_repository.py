"""Read and write user preferences."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.db.preference import UserPreferenceRecord


# Consent for webcam capture. Absent means "not granted": emotion detection is
# opt-in, so a fresh install never opens the camera until someone says yes.
WEBCAM_EMOTION_CONSENT = "webcam_emotion_consent"


class PreferenceRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_bool(self, user_id: str, key: str, default: bool = False) -> bool:
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        if row is None:
            return default
        return row.value == "true"

    def set_bool(self, user_id: str, key: str, value: bool) -> bool:
        stored = "true" if value else "false"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = self.db.get(UserPreferenceRecord, (user_id, key))
        if row is None:
            self.db.add(
                UserPreferenceRecord(
                    user_id=user_id, key=key, value=stored, updated_at=now
                )
            )
        else:
            row.value = stored
            row.updated_at = now
        self.db.commit()
        return value
