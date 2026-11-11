from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics_service import AnalyticsService

router = APIRouter(tags=["Analytics"])

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MEDIA_TYPE = "application/pdf"


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def analytics_summary(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    department: Annotated[str | None, Query(max_length=100)] = None,
) -> AnalyticsSummaryResponse:
    return await AnalyticsService(session).summary(
        current_user,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        location=location,
        department=department,
    )


@router.get("/export/project-progress", response_model=None)
async def export_project_progress(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    department: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    data = await AnalyticsService(session).project_progress_export(
        current_user,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        location=location,
        department=department,
    )
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="project-progress.xlsx"'},
    )


@router.get("/export/material-usage", response_model=None)
async def export_material_usage(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    department: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    data = await AnalyticsService(session).material_usage_export(
        current_user,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        department=department,
    )
    return Response(
        content=data,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="material-usage.xlsx"'},
    )


@router.get("/export/management-summary", response_model=None)
async def export_management_summary(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    location: Annotated[str | None, Query(max_length=100)] = None,
    department: Annotated[str | None, Query(max_length=100)] = None,
) -> Response:
    data = await AnalyticsService(session).management_pdf_summary(
        current_user,
        project_id=project_id,
        date_from=date_from,
        date_to=date_to,
        location=location,
        department=department,
    )
    return Response(
        content=data,
        media_type=PDF_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="management-summary.pdf"'},
    )
