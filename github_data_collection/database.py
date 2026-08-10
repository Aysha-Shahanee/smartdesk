import json
import time
from pathlib import Path
from typing import Dict, List

from sqlalchemy import create_engine, Column, Integer, String, Text, event, UniqueConstraint, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

BASE_DIR = Path(__file__).resolve().parent
DB_DIR = BASE_DIR / "storage"
DB_FILE = DB_DIR / "github_data.db"
DB_URL = settings.GITHUB_DATABASE_URL

DB_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
    poolclass=NullPool,
    connect_args={"check_same_thread": False, "timeout": 30},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, future=True, expire_on_commit=False)
Base = declarative_base()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


def _retry_db_operation(func):
    def wrapper(*args, **kwargs):
        max_attempts = 6
        for attempt in range(1, max_attempts + 1):
            try:
                return func(*args, **kwargs)
            except OperationalError as exc:
                message = str(exc).lower()
                if "database is locked" in message and attempt < max_attempts:
                    time.sleep(0.5 * attempt)
                    continue
                raise
    return wrapper


class PreviousStatus(Base):
    __tablename__ = "previous_status"

    project_item_id = Column(String(255), primary_key=True)
    status = Column(String(128), nullable=False)


class ActiveTask(Base):
    __tablename__ = "active_tasks"

    project_item_id = Column(String(255), primary_key=True)
    issue_id = Column(String(255), nullable=False)
    title = Column(Text, default="")
    started_at = Column(String(64), nullable=False)
    smartdesk_user_id = Column(String(255), nullable=True, index=True)
    project_id = Column(String(255), nullable=True, index=True)
    repository = Column(String(255), nullable=True)


class CollectedTask(Base):
    __tablename__ = "collected_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_item_id = Column(String(255), nullable=False)
    issue_id = Column(String(255), nullable=False)
    title = Column(Text)
    description = Column(Text)
    status = Column(String(128))
    priority = Column(String(128))
    labels = Column(Text)
    assignees = Column(Text)
    comments_count = Column(Integer)
    created_at = Column(String(64))
    updated_at = Column(String(64))
    # detected_start_time is retained for backward compatibility. New code
    # treats started_at/completed_at as the lifecycle source of truth.
    detected_start_time = Column(String(64), nullable=False)
    started_at = Column(String(64), nullable=True)
    completed_at = Column(String(64), nullable=True)
    smartdesk_user_id = Column(String(255), nullable=True, index=True)
    project_id = Column(String(255), nullable=True, index=True)
    repository = Column(String(255), nullable=True)


class SampleCollection(Base):
    __tablename__ = "sample_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collected_at = Column(String(64), nullable=False)
    tasks = Column(Text, nullable=False)
    statuses = Column(Text, nullable=False)


class ProjectItemState(Base):
    __tablename__ = "project_item_state"

    project_item_id = Column(String(255), primary_key=True)
    project_id = Column(String(255), nullable=False, index=True)
    status_option_name = Column(String(128))
    logical_status = Column(String(32), nullable=False)
    updated_at = Column(String(64), nullable=False)


class ProjectStatusMapping(Base):
    __tablename__ = "project_status_mapping"
    __table_args__ = (
        UniqueConstraint("project_id", "status_option_name", name="uq_project_status_mapping"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(255), nullable=False, index=True)
    status_option_name = Column(String(128), nullable=False)
    logical_status = Column(String(32), nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    delivery_id = Column(String(255), primary_key=True)
    processed_at = Column(String(64), nullable=False)


def init_db() -> None:
    """Create tables and apply additive, data-preserving schema upgrades."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("collected_tasks")}
    with engine.begin() as connection:
        if "started_at" not in columns:
            connection.execute(text("ALTER TABLE collected_tasks ADD COLUMN started_at VARCHAR(64)"))
        if "completed_at" not in columns:
            connection.execute(text("ALTER TABLE collected_tasks ADD COLUMN completed_at VARCHAR(64)"))
        if "smartdesk_user_id" not in columns:
            connection.execute(text("ALTER TABLE collected_tasks ADD COLUMN smartdesk_user_id VARCHAR(255)"))
        if "project_id" not in columns:
            connection.execute(text("ALTER TABLE collected_tasks ADD COLUMN project_id VARCHAR(255)"))
        if "repository" not in columns:
            connection.execute(text("ALTER TABLE collected_tasks ADD COLUMN repository VARCHAR(255)"))
        connection.execute(text(
            "UPDATE collected_tasks SET started_at = detected_start_time "
            "WHERE started_at IS NULL"
        ))
        active_columns = {column["name"] for column in inspector.get_columns("active_tasks")}
        if "smartdesk_user_id" not in active_columns:
            connection.execute(text("ALTER TABLE active_tasks ADD COLUMN smartdesk_user_id VARCHAR(255)"))
        if "project_id" not in active_columns:
            connection.execute(text("ALTER TABLE active_tasks ADD COLUMN project_id VARCHAR(255)"))
        if "repository" not in active_columns:
            connection.execute(text("ALTER TABLE active_tasks ADD COLUMN repository VARCHAR(255)"))


init_db()


def _encode_list(value):
    if value is None:
        return json.dumps([])
    return json.dumps(value)


def _decode_list(value):
    if not value:
        return []
    try:
        return json.loads(value)
    except Exception:
        return []


@_retry_db_operation
def save_collected_task(metadata: dict) -> None:
    with SessionLocal() as session:
        task = CollectedTask(
            project_item_id=metadata.get("project_item_id"),
            issue_id=metadata.get("issue_id"),
            title=metadata.get("title"),
            description=metadata.get("description"),
            status=metadata.get("status"),
            priority=metadata.get("priority"),
            labels=_encode_list(metadata.get("labels")),
            assignees=_encode_list(metadata.get("assignees")),
            comments_count=metadata.get("comments_count"),
            created_at=metadata.get("created_at"),
            updated_at=metadata.get("updated_at"),
            detected_start_time=metadata.get("detected_start_time"),
            started_at=metadata.get("started_at") or metadata.get("detected_start_time"),
            completed_at=metadata.get("completed_at"),
            smartdesk_user_id=metadata.get("smartdesk_user_id"),
            project_id=metadata.get("project_id"),
            repository=metadata.get("repository"),
        )
        session.add(task)
        session.commit()


@_retry_db_operation
def save_sample_collection(tasks: List[Dict], statuses: List[Dict], collected_at: str) -> None:
    with SessionLocal() as session:
        sample = SampleCollection(
            collected_at=collected_at,
            tasks=json.dumps(tasks),
            statuses=json.dumps(statuses),
        )
        session.add(sample)
        session.commit()


@_retry_db_operation
def load_active_tasks() -> list[dict]:
    with SessionLocal() as session:
        tasks = session.query(ActiveTask).all()
        return [
            {
                "project_item_id": row.project_item_id,
                "issue_id": row.issue_id,
                "title": row.title,
                "started_at": row.started_at,
            }
            for row in tasks
        ]


@_retry_db_operation
def load_previous_statuses() -> dict[str, str]:
    with SessionLocal() as session:
        rows = session.query(PreviousStatus).all()
        return {row.project_item_id: row.status for row in rows}


@_retry_db_operation
def save_previous_statuses(status_map: dict[str, str]) -> None:
    with SessionLocal() as session:
        existing = {row.project_item_id: row for row in session.query(PreviousStatus).all()}

        for project_item_id, status in status_map.items():
            if project_item_id in existing:
                existing[project_item_id].status = status
            else:
                session.add(PreviousStatus(project_item_id=project_item_id, status=status))

        for project_item_id in set(existing) - set(status_map):
            session.delete(existing[project_item_id])

        session.commit()


@_retry_db_operation
def add_active_task(project_item_id: str, issue_id: str, title: str, started_at: str,
                    smartdesk_user_id: str | None = None,
                    project_id: str | None = None) -> None:
    with SessionLocal() as session:
        existing = session.get(ActiveTask, project_item_id)
        if existing:
            return
        session.add(
            ActiveTask(
                project_item_id=project_item_id,
                issue_id=issue_id,
                title=title,
                started_at=started_at,
                smartdesk_user_id=smartdesk_user_id,
                project_id=project_id,
                repository=None,
            )
        )
        session.commit()


@_retry_db_operation
def remove_active_task(project_item_id: str) -> None:
    with SessionLocal() as session:
        active_task = session.get(ActiveTask, project_item_id)
        if active_task:
            session.delete(active_task)
            session.commit()
