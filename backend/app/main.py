import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.routes import dashboard
from app.routes import health
from app.routes import ingest
from app.routes import calendar
from app.routes import github
from app.services.calendar_auth_service import CalendarAuthService
from app.services.github_collector import github_collector_job
from app.services.calendar_sync_job import CalendarSyncJob
from app.services.calendar_sync_service import CalendarSyncService
from app.services.os_collector import OSCollector
from app.services.session_timeout_job import SessionTimeoutJob
from app.services.work_period_scheduler import WorkPeriodScheduler

logger = logging.getLogger("smartdesk.main")

# Background jobs — instantiated at module load so they are singletons.
_timeout_job = SessionTimeoutJob()
_work_scheduler = WorkPeriodScheduler()
_os_collector = OSCollector()
_calendar_auth = CalendarAuthService(
    credentials_file=settings.GOOGLE_CALENDAR_CREDENTIALS_FILE,
    token_file=settings.GOOGLE_CALENDAR_TOKEN_FILE,
    scopes=settings.GOOGLE_CALENDAR_SCOPES,
    redirect_uri=settings.GOOGLE_CALENDAR_REDIRECT_URI,
    state_file=settings.GOOGLE_CALENDAR_OAUTH_STATE_FILE,
)
_calendar_sync = CalendarSyncService(
    auth_service=_calendar_auth,
    sync_state_file=settings.GOOGLE_CALENDAR_SYNC_STATE_FILE,
)
_calendar_job = CalendarSyncJob(_calendar_sync)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=settings.LOG_LEVEL)
    logger.info("SmartDesk backend started.")

    # Start background jobs
    _timeout_job.start()
    _work_scheduler.start()
    _os_collector.start()
    _calendar_job.start()
    github_collector_job.start()

    yield

    # Graceful shutdown
    _os_collector.stop()
    _timeout_job.stop()
    _work_scheduler.stop()
    _calendar_job.stop()
    github_collector_job.stop()
    logger.info("SmartDesk backend stopped.")


from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="SmartDesk Session Backend", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    print(f"422 Validation Error on {request.url}:")
    print(exc.errors())
    body = await request.body()
    print(f"Body: {body.decode('utf-8', errors='replace')}")
    
    with open("validation_errors.log", "a") as f:
        f.write(f"URL: {request.url}\n")
        f.write(f"Errors: {exc.errors()}\n")
        f.write(f"Body: {body.decode('utf-8', errors='replace')}\n")
        f.write("-" * 40 + "\n")

    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()}
    )

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
app.include_router(github.router, prefix="/api/v1/github", tags=["GitHub"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])


@app.get("/")
def root():
    return {
        "service": "SmartDesk Session Backend",
        "status": "running",
        "architecture": "session-based",
        "background_jobs": [
            "session_timeout_job",
            "work_period_scheduler",
            "os_collector",
            "calendar_sync",
            "github_collector",
        ],
    }
