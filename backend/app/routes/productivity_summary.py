from fastapi import APIRouter, Depends, Query
from app.models.productivity_summary import ProductivitySummaryBuildRequest
from app.services.productivity_summary_service import ProductivitySummaryService

router = APIRouter()


def get_service():
    return ProductivitySummaryService()


@router.get("/10min")
def list_summaries(
    user_id: str | None = Query(default=None),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: ProductivitySummaryService = Depends(get_service),
):
    rows = service.list(user_id=user_id, start_time=start_time, end_time=end_time, limit=limit)
    results = [{column.name: getattr(row, column.name) for column in row.__table__.columns} for row in rows]
    return {
        "count": len(results),
        "results": results,
    }


@router.post("/10min/build")
def build_summaries(
    payload: ProductivitySummaryBuildRequest,
    service: ProductivitySummaryService = Depends(get_service),
):
    result = service.build(payload.user_id, payload.start_time, payload.end_time)
    return {"message": "Build completed", "result": result}
