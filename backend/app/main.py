import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import Base, engine
from app.core.logging import setup_logging
from app.models import db_models  # noqa: F401  — registers ORM models with Base
from app.routes import (
    activity_session_summary,
    browser,
    calendar,
    dashboard,
    health,
    github_integration,
    ide,
    os_minute_window,
)

logger = logging.getLogger("smartdesk.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Configure logging first
    setup_logging(level=settings.LOG_LEVEL)

    # Initialize the database file and tables on startup
    logger.info("Initializing local SQLite database...")
    Base.metadata.create_all(bind=engine)

    from app.services.os_monitoring_service import os_monitor
    from app.services.calendar_sync_service import calendar_sync
    from app.services.activity_session_summary_scheduler import activity_session_scheduler

    logger.info("Starting OS Collector background service...")
    os_monitor.start()
    logger.info("Starting Calendar Collector background service...")
    calendar_sync.start()
    logger.info("Starting Activity Session Scheduler...")
    activity_session_scheduler.start()
    yield
    logger.info("Stopping OS Collector background service...")
    os_monitor.stop()
    logger.info("Stopping Calendar Collector background service...")
    calendar_sync.stop()
    logger.info("Stopping Activity Session Scheduler...")
    activity_session_scheduler.stop()


app = FastAPI(title="SmartDesk Data Collection Layer", lifespan=lifespan)

# CORS — restricted to configured origins (extensions + local dev servers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(os_minute_window.router, prefix="/api/v1/os", tags=["OS Minute Windows"])
app.include_router(browser.router, prefix="/api/v1/browser", tags=["Browser"])
app.include_router(ide.router, prefix="/api/v1/ide", tags=["IDE"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"])
app.include_router(github_integration.router, prefix="/api/v1/integrations/github", tags=["GitHub Integration"])
app.include_router(activity_session_summary.router, prefix="/api/v1/activity-sessions", tags=["Activity Sessions"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])


@app.get("/")
def root():
    return {"message": "Welcome to SmartDesk Data Collection API"}
