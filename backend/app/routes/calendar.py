from fastapi import APIRouter, Depends
from app.models.calendar import CalendarPayload
from app.services.calendar_service import CalendarService


router = APIRouter()


def get_service():
    return CalendarService()


@router.post("/")
def collect_data(payload: CalendarPayload, service: CalendarService = Depends(get_service)):
    result = service.process_and_save(payload)
    return {"message": "Data collected successfully", "result": result}
