from fastapi import APIRouter, Depends, Query
from app.models.os_minute_window import OSMinuteWindowPayload
from app.services.os_minute_window_service import OSMinuteWindowService

router = APIRouter()


def get_service():
    return OSMinuteWindowService()


@router.post("/minute-window")
def collect_minute_window(
    payload: OSMinuteWindowPayload,
    service: OSMinuteWindowService = Depends(get_service),
):
    result = service.process_and_save(payload)
    return {"message": "OS minute window collected successfully", "result": result}


@router.get("/minute-window")
def list_minute_windows(
    user_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: OSMinuteWindowService = Depends(get_service),
):
    rows = service.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)
    results = [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows]
    return {"count": len(results), "results": results}
