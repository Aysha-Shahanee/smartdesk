from sqlalchemy import Column
from sqlalchemy import String

from app.core.database import Base


class ServiceHeartbeatRecord(Base):
    """Single-row liveness marker: the last time the backend was observed alive.

    Session rows record when a window gained focus, but nothing recorded whether
    the collector was still *running* to see it end.  Without that, a process
    that stops with a session open has the whole outage credited to whatever
    window happened to be in front when it died.  This table is the missing
    signal: the timeout job stamps it every tick, so a frozen value marks the
    moment the observer stopped.
    """

    __tablename__ = "service_heartbeat"

    id = Column(String, primary_key=True)
    beat_at = Column(String, nullable=False)
