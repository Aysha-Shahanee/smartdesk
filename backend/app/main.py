import os
from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging import setup_logging
from app.routes import calendar
from app.routes import dashboard
from app.routes import emotion
from app.routes import health
from app.routes import ingest
from app.routes import github_integration
from app.routes import recommendations
from app.routes import reports
from app.routes import segment_feedback
from app.routes import window_clusters
from app.services.activity_segment_builder import ActivitySegmentBuilder
from app.services.calendar_sync_job import CalendarSyncJob
from app.services.liveness import get_last_heartbeat
from app.services.liveness import reconcile_open_sessions
from app.services.os_collector import OSCollector
from app.services.recommendation_job import RecommendationJob
from app.services.session_timeout_job import SessionTimeoutJob
from app.services.work_period_scheduler import WorkPeriodScheduler

logger = logging.getLogger("smartdesk.main")

# Background jobs — instantiated at module load so they are singletons.
_timeout_job = SessionTimeoutJob()
_work_scheduler = WorkPeriodScheduler()
_os_collector = OSCollector()
_calendar_sync_job = CalendarSyncJob()
_activity_segment_builder = ActivitySegmentBuilder(
    user_id=settings.DEFAULT_USER_ID,
    device_id=settings.DEVICE_ID,
)
_recommendation_job = RecommendationJob(user_id=settings.DEFAULT_USER_ID)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=settings.LOG_LEVEL)
    logger.info("SmartDesk backend started.")

    # Close sessions orphaned by the previous process BEFORE the collector runs.
    # Its first tick always emits 'focused' (_last_app is None), which would
    # close them at *now* and bill the whole downtime as activity. The timeout
    # job cannot do this either — it fires on a 60 s timer and loses the race.
    db = SessionLocal()
    try:
        reconcile_open_sessions(db, get_last_heartbeat(db))
    except Exception:
        logger.exception("Startup reconciliation failed; continuing.")
        db.rollback()
    finally:
        db.close()

    # Start background jobs
    _timeout_job.start()
    _work_scheduler.start()
    _os_collector.start()
    _calendar_sync_job.start()
    _activity_segment_builder.start()
    _recommendation_job.start()

    yield

    # Graceful shutdown
    emotion.stop_emotion_service_if_running()
    _recommendation_job.stop()
    _activity_segment_builder.stop()
    _calendar_sync_job.stop()
    _os_collector.stop()
    _timeout_job.stop()
    _work_scheduler.stop()
    logger.info("SmartDesk backend stopped.")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="SmartDesk Session Backend", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Log rejected payloads — a collector sending a bad schema would
    otherwise lose data silently."""
    body = await request.body()
    logger.warning(
        "422 on %s: %s | body: %s",
        request.url.path,
        exc.errors(),
        body.decode("utf-8", errors="replace")[:2000],
    )
    return JSONResponse(status_code=422, content={"detail": exc.errors()})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(ingest.router, prefix="/api/v1/ingest", tags=["Ingest"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"])
app.include_router(emotion.router, prefix="/api/v1/emotion", tags=["Emotion"])
app.include_router(
    github_integration.router,
    prefix="/api/v1/integrations/github",
    tags=["GitHub Integration"],
)
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(segment_feedback.router, prefix="/api/v1/activity-segments", tags=["Segment Feedback"])
app.include_router(window_clusters.router, prefix="/api/v1", tags=["Window Clusters"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["Recommendations"])
app.include_router(reports.router, prefix="/api/v1", tags=["Reports"])


@app.get("/")
def root():
    return {
        "service": "SmartDesk Session Backend",
        "status": "running",
        "architecture": "session-based",
        "timezone": settings.TIMEZONE,
        "background_jobs": [
            "session_timeout_job",
            "work_period_scheduler",
            "os_collector",
            "calendar_sync_job",
            "activity_segment_builder",
            "emotion_detection_api",
            "recommendation_job",
        ],
        "dashboard_ui": "/dashboard/ui",
    }
