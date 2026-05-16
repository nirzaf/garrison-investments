from fastapi import APIRouter
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(tags=["Analytics"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    current_user: CurrentUser,
    session: DbSession,
) -> AnalyticsSummaryResponse:
    return await AnalyticsService(session).summary(current_user)


@router.get("/export/project-progress")
async def export_project_progress(current_user: CurrentUser, session: DbSession) -> Response:
    data = await AnalyticsService(session).project_progress_export(current_user)
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="project-progress.xlsx"'},
    )


@router.get("/export/material-usage")
async def export_material_usage(current_user: CurrentUser, session: DbSession) -> Response:
    data = await AnalyticsService(session).material_usage_export(current_user)
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="material-usage.xlsx"'},
    )
