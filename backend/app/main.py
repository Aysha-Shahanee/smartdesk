import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.routes import calendar
from app.routes import dashboard
from app.routes import health
from app.routes import ingest
from app.services.calendar_sync_job import CalendarSyncJob
from app.services.os_collector import OSCollector
from app.services.session_timeout_job import SessionTimeoutJob
from app.services.work_period_scheduler import WorkPeriodScheduler

logger = logging.getLogger("smartdesk.main")

# Background jobs — instantiated at module load so they are singletons.
_timeout_job = SessionTimeoutJob()
_work_scheduler = WorkPeriodScheduler()
_os_collector = OSCollector()
_calendar_sync_job = CalendarSyncJob()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=settings.LOG_LEVEL)
    logger.info("SmartDesk backend started.")

    # Start background jobs
    _timeout_job.start()
    _work_scheduler.start()
    _os_collector.start()
    _calendar_sync_job.start()

    yield

    # Graceful shutdown
    _calendar_sync_job.stop()
    _os_collector.stop()
    _timeout_job.stop()
    _work_scheduler.stop()
    logger.info("SmartDesk backend stopped.")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="SmartDesk Session Backend", lifespan=lifespan)


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
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(ingest.router, prefix="/api/v1/ingest", tags=["Ingest"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])


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
        ],
        "dashboard_ui": "/dashboard/ui",
    }
