"""Per-user preference storage.

Settings toggles that gate data collection have to survive a restart and be
readable by the backend that does the collecting — a value kept only in the
renderer's localStorage cannot stop a capture loop that runs in the API
process. This table is the one place those answers live.
"""

from sqlalchemy import Column, String

from app.core.database import Base


class UserPreferenceRecord(Base):
    """A single named preference for a user, stored as text."""

    __tablename__ = "user_preferences"

    user_id = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
