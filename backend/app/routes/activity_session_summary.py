from fastapi import APIRouter, Depends, Query

from app.models.activity_session_summary import ActivitySessionBuildRequest
from app.services.activity_session_summary_service import ActivitySessionSummaryService

router = APIRouter()


def get_service():
    return ActivitySessionSummaryService()


@router.get("")
def list_sessions(
    user_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    service: ActivitySessionSummaryService = Depends(get_service),
):
    rows = service.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)
    results = [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows]
    return {
        "count": len(results),
        "results": results,
    }


@router.post("/build")
def build_sessions(
    payload: ActivitySessionBuildRequest,
    service: ActivitySessionSummaryService = Depends(get_service),
):
    result = service.build(payload.user_id, payload.start_time, payload.end_time)
    return {"message": "Build completed", "result": result}
