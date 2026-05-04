from fastapi import APIRouter
from app.services.calendar_service import CalendarService

router = APIRouter()
calendar_service = CalendarService()

@router.get("/status")
def get_calendar_status():
    return calendar_service.get_status()

@router.post("/connect")
def connect_calendar(force_reauth: bool = False):
    return calendar_service.connect(force_reauth=force_reauth)

@router.post("/disconnect")
def disconnect_calendar():
    return calendar_service.disconnect()

@router.post("/sync")
def sync_calendar():
    return calendar_service.sync_now()
