import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import setup_logging
from app.routes import dashboard
from app.routes import health
from app.routes import ingest
from app.routes import legacy
from app.services.os_collector import OSCollector
from app.services.session_timeout_job import SessionTimeoutJob
from app.services.work_period_scheduler import WorkPeriodScheduler

logger = logging.getLogger("smartdesk.main")

# Background jobs — instantiated at module load so they are singletons.
_timeout_job = SessionTimeoutJob()
_work_scheduler = WorkPeriodScheduler()
_os_collector = OSCollector()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(level=settings.LOG_LEVEL)
    logger.info("SmartDesk backend started.")

    # Start background jobs
    _timeout_job.start()
    _work_scheduler.start()
    _os_collector.start()

    yield

    # Graceful shutdown
    _os_collector.stop()
    _timeout_job.stop()
    _work_scheduler.stop()
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
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
app.include_router(legacy.router, prefix="/api/v1", tags=["Legacy (deprecated)"])


@app.get("/")
def root():
    return {
        "service": "SmartDesk Session Backend",
        "status": "running",
        "architecture": "session-based",
        "background_jobs": ["session_timeout_job", "work_period_scheduler", "os_collector"],
    }
