from sqlalchemy import Column, Integer, String, DateTime, JSON
from app.core.database import Base


class OSSignalRecord(Base):
    __tablename__ = "os_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)  # Stores the raw dictionary natively


class BrowserRecord(Base):
    __tablename__ = "browser_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class VSCodeRecord(Base):
    __tablename__ = "vscode_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)


class CalendarRecord(Base):
    __tablename__ = "calendar_signals"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), index=True)
    event_type = Column(String, index=True)
    data = Column(JSON)
