"""
Shared pytest fixtures for the SmartDesk backend test suite.

Uses a temporary SQLite test database (test_smartdesk.db) so no production
data is touched. Tables are created once per session; all rows are deleted
between each test so every test starts with a clean slate.
"""
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app

# ── One test database for the entire pytest session ────────────────────────

TEST_DB_PATH = "test_smartdesk.db"
TEST_DB_URL  = f"sqlite:///./{TEST_DB_PATH}"

_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})

# Drop + recreate completely fresh — this runs once at import time
Base.metadata.drop_all(_engine)
Base.metadata.create_all(_engine)

_Session = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


# ── Per-test fixtures ──────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_tables():
    """Delete all rows from every table before each test."""
    session = _Session()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()


@pytest.fixture
def db():
    """Yield a fresh session for the test, close it after."""
    session = _Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    """TestClient with the test DB session injected via dependency override."""

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
