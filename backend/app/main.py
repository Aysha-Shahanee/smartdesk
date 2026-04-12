from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import health, os_signals, browser, vscode, calendar, dashboard
from app.core.database import Base, engine
from app.models import db_models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database file and tables on startup
    print("Initializing local SQLite database...")
    Base.metadata.create_all(bind=engine)
    
    from app.services.os_monitoring_service import os_monitor
    from app.services.calendar_sync_service import calendar_sync
    print("Starting OS Collector background service...")
    os_monitor.start()
    print("Starting Calendar Collector background service...")
    calendar_sync.start()
    yield
    print("Stopping OS Collector background service...")
    os_monitor.stop()
    print("Stopping Calendar Collector background service...")
    calendar_sync.stop()

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
app.include_router(os_signals.router, prefix="/api/v1/os-signals", tags=["OS Signals"])
app.include_router(browser.router, prefix="/api/v1/browser", tags=["Browser"])
app.include_router(vscode.router, prefix="/api/v1/vscode", tags=["VS Code"])
app.include_router(calendar.router, prefix="/api/v1/calendar", tags=["Calendar"])
app.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

@app.get("/")
def root():
    return {"message": "Welcome to SmartDesk Data Collection API"}
