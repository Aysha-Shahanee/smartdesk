"""SmartDesk v2 detection storage models."""

from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text

from app.core.database import Base


class SmartDeskDetectionSessionRecord(Base):
    """One webcam detection session from the v2 SmartDesk brain."""

    __tablename__ = "smartdesk_detection_sessions"
    __table_args__ = (
        Index("ix_smartdesk_detection_sessions_user_real_start", "user_id", "real_start_time"),
        Index("ix_smartdesk_detection_sessions_status", "status"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    program_start_time = Column(String, nullable=False)
    warmup_end_time = Column(String, nullable=True)
    real_start_time = Column(String, nullable=True)
    actual_camera_end_time = Column(String, nullable=True)
    usable_block_end_time = Column(String, nullable=True)
    discarded_tail_seconds = Column(Float, nullable=False, default=0.0)
    startup_wait_seconds_after_warmup = Column(Float, nullable=False, default=0.0)
    official_seconds_requested = Column(Float, nullable=False, default=0.0)
    sample_fps = Column(Float, nullable=False, default=0.0)
    frames_read = Column(Integer, nullable=False, default=0)
    samples_processed = Column(Integer, nullable=False, default=0)
    face_detected_samples = Column(Integer, nullable=False, default=0)
    completed_counts_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class SmartDeskSignalBlockRecord(Base):
    """Low-level v2 signal block: emotion 10s, engagement 10s, or sleepiness 60s."""

    __tablename__ = "smartdesk_signal_blocks"
    __table_args__ = (
        Index("ix_smartdesk_signal_blocks_session_start", "session_id", "block_start_time"),
        Index("ix_smartdesk_signal_blocks_user_start", "user_id", "block_start_time"),
        Index("ix_smartdesk_signal_blocks_type_start", "block_type", "block_start_time"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    block_type = Column(String, nullable=False)
    block_start_time = Column(String, nullable=False)
    block_end_time = Column(String, nullable=False)
    window_seconds = Column(Float, nullable=False)
    total_time = Column(Float, nullable=False)
    ready = Column(Boolean, nullable=False, default=False)

    valid_frame_count = Column(Integer, nullable=False, default=0)
    happy_avg = Column(Float, nullable=False, default=0.0)
    neutral_avg = Column(Float, nullable=False, default=0.0)
    confusion_avg = Column(Float, nullable=False, default=0.0)
    top_class = Column(String, nullable=True)
    top_probability = Column(Float, nullable=False, default=0.0)
    emotion_state = Column(String, nullable=True)
    emotion_sublabel = Column(String, nullable=True)

    face_visible_ratio = Column(Float, nullable=False, default=0.0)
    screen_facing_ratio = Column(Float, nullable=False, default=0.0)
    looking_away_ratio = Column(Float, nullable=False, default=0.0)
    long_lookaway_count = Column(Integer, nullable=False, default=0)
    engagement_label = Column(String, nullable=True)

    perclos = Column(Float, nullable=False, default=0.0)
    eye_closed_ratio = Column(Float, nullable=False, default=0.0)
    head_down_ratio = Column(Float, nullable=False, default=0.0)
    possible_yawn_ratio = Column(Float, nullable=False, default=0.0)
    long_eye_closure_count = Column(Integer, nullable=False, default=0)
    yawn_count = Column(Integer, nullable=False, default=0)
    sleepiness_label = Column(String, nullable=True)

    raw_summary_json = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class SmartDeskFinalStateBlockRecord(Base):
    """Five-minute fused v2 work-state block."""

    __tablename__ = "smartdesk_final_state_blocks"
    __table_args__ = (
        Index("ix_smartdesk_final_state_blocks_session_start", "session_id", "block_start_time"),
        Index("ix_smartdesk_final_state_blocks_user_start", "user_id", "block_start_time"),
        Index("ix_smartdesk_final_state_blocks_state_start", "state", "block_start_time"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    block_start_time = Column(String, nullable=False)
    block_end_time = Column(String, nullable=False)
    window_seconds = Column(Float, nullable=False)
    state = Column(String, nullable=True)
    matched_rule = Column(String, nullable=False)
    ready = Column(Boolean, nullable=False, default=False)
    confusion_ratio = Column(Float, nullable=False, default=0.0)
    stable_emotion_ratio = Column(Float, nullable=False, default=0.0)
    engaged_ratio = Column(Float, nullable=False, default=0.0)
    low_engagement_ratio = Column(Float, nullable=False, default=0.0)
    drowsy_ratio = Column(Float, nullable=False, default=0.0)
    emotion_confusion_count = Column(Integer, nullable=False, default=0)
    emotion_stable_count = Column(Integer, nullable=False, default=0)
    engagement_high_count = Column(Integer, nullable=False, default=0)
    engagement_medium_count = Column(Integer, nullable=False, default=0)
    engagement_low_count = Column(Integer, nullable=False, default=0)
    sleepiness_alert_count = Column(Integer, nullable=False, default=0)
    sleepiness_drowsy_count = Column(Integer, nullable=False, default=0)
    dominant_emotion = Column(String, nullable=True)
    dominant_engagement = Column(String, nullable=True)
    dominant_sleepiness = Column(String, nullable=True)
    raw_summary_json = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class SmartDeskReportingBlockRecord(Base):
    """Fifteen-minute dashboard/reporting v2 work-state summary."""

    __tablename__ = "smartdesk_reporting_blocks"
    __table_args__ = (
        Index("ix_smartdesk_reporting_blocks_session_start", "session_id", "block_start_time"),
        Index("ix_smartdesk_reporting_blocks_user_start", "user_id", "block_start_time"),
        Index("ix_smartdesk_reporting_blocks_state_start", "dominant_state", "block_start_time"),
    )

    id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False)
    session_id = Column(String, nullable=False)
    block_start_time = Column(String, nullable=False)
    block_end_time = Column(String, nullable=False)
    window_seconds = Column(Float, nullable=False)
    final_state_block_count = Column(Integer, nullable=False, default=0)
    focused_ratio = Column(Float, nullable=False, default=0.0)
    struggling_ratio = Column(Float, nullable=False, default=0.0)
    disengaged_ratio = Column(Float, nullable=False, default=0.0)
    fatigued_ratio = Column(Float, nullable=False, default=0.0)
    overloaded_ratio = Column(Float, nullable=False, default=0.0)
    dominant_state = Column(String, nullable=True)
    ready = Column(Boolean, nullable=False, default=False)
    raw_summary_json = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)
