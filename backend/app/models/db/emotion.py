"""Local emotion detection storage models."""

from sqlalchemy import Column, Float, Index, Integer, String, Text

from app.core.database import Base


class EmotionSessionRecord(Base):
    """Emotion detection session stored in the local SmartDesk database."""

    __tablename__ = "emotion_sessions"
    __table_args__ = (
        Index("ix_emotion_sessions_user_started", "user_id", "started_at"),
        Index("ix_emotion_sessions_status", "status"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    session_number = Column(Integer, nullable=True)
    started_at = Column(String, nullable=False)
    ended_at = Column(String, nullable=True)
    status = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class EmotionBlockRecord(Base):
    """Completed emotion block stored locally for dashboard reads."""

    __tablename__ = "emotion_blocks"
    __table_args__ = (
        Index("ix_emotion_blocks_session_start", "session_id", "block_start_time"),
        Index("ix_emotion_blocks_user_start", "user_id", "block_start_time"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    session_start_time = Column(String, nullable=False)
    block_start_time = Column(String, nullable=False)
    block_end_time = Column(String, nullable=False)
    block_type = Column(String, nullable=False)
    duration_minutes = Column(Float, nullable=False)
    dominant_emotion = Column(String, nullable=False)
    happy_score = Column(Float, nullable=False, default=0.0)
    neutral_score = Column(Float, nullable=False, default=0.0)
    angry_score = Column(Float, nullable=False, default=0.0)
    surprise_score = Column(Float, nullable=False, default=0.0)
    emotion_scores = Column(Text, nullable=False)
    processed_frame_count = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)
