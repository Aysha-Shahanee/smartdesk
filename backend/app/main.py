from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import (
    activity_session_summary,
    browser,
    calendar,
    dashboard,
    health,
    os_minute_window,
    vscode,
)
from app.core.database import Base, engine
from app.models import db_models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run schema migrations before table creation
    print("Running database migrations...")
    from pathlib import Path
    from app.core.database import engine
    migration_files = [
        Path(__file__).parent.parent / "scripts" / "migrations" / "006_create_activity_session_summary.sql",
        Path(__file__).parent.parent / "scripts" / "migrations" / "007_drop_activity_session_summary_fields.sql",
    ]
    for migration_sql in migration_files:
        if migration_sql.exists():
            with engine.connect() as conn:
                sql_text = migration_sql.read_text(encoding="utf-8")
                # Strip line comments before splitting to avoid semicolons in comments.
                sql_text = "\n".join(
                    line for line in sql_text.splitlines() if not line.strip().startswith("--")
                )
                for statement in sql_text.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        try:
                            conn.execute(__import__("sqlalchemy").text(stmt))
                        except Exception as e:
                            print(f"[Migration] Warning: {e}")
                conn.commit()
            print(f"Migration {migration_sql.name} applied.")

    # Initialize the database file and tables on startup
    print("Initializing local SQLite database...")
    Base.metadata.create_all(bind=engine)

    
    from app.services.os_monitoring_service import os_monitor
    from app.services.calendar_sync_service import calendar_sync
    from app.services.activity_session_summary_scheduler import activity_session_scheduler
    print("Starting OS Collector background service...")
    os_monitor.start()
    print("Starting Calendar Collector background service...")
    calendar_sync.start()
    activity_session_scheduler.start()
    yield
    print("Stopping OS Collector background service...")
    os_monitor.stop()
    print("Stopping Calendar Collector background service...")
    calendar_sync.stop()
    activity_session_scheduler.stop()

app = FastAPI(title="SmartDesk Data Collection Layer", lifespan=lifespan)

# Add CORS middleware to allow requests from Chrome/Edge extensions
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (including chrome-extension://)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(os_minute_window.router, prefix="/api/v1/os", tags=["OS Minute Windows"])
app.include_router(browser.router, prefix="/api/v1/browser", tags=["Browser"])
app.include_router(vscode.router, prefix="/api/v1/vscode", tags=["VS Code"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"])
app.include_router(activity_session_summary.router, prefix="/api/v1/activity-sessions", tags=["Activity Sessions"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

@app.get("/")
def root():
    return {"message": "Welcome to SmartDesk Data Collection API"}
