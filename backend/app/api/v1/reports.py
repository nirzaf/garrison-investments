from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status
from fastapi.responses import Response

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.daily_reports import (
    DailyReportCreateRequest,
    DailyReportDecisionRequest,
    DailyReportListResponse,
    DailyReportOverrideRequest,
    DailyReportResponse,
    DailyReportUpdateRequest,
)
from app.schemas.projects import ProjectOption, ProjectOptionListResponse
from app.schemas.supervisor_updates import SupervisorUpdateResponse
from app.services.idempotency import validate_key
from app.services.project_service import ProjectService
from app.services.report_export_service import PDF_CONTENT_TYPE, ReportExportService
from app.services.report_service import ReportService
from app.services.reporting_service import ReportingService
from app.utils.exceptions import AppException

router = APIRouter(prefix="/reports", tags=["Daily Reports"])


@router.get("/project-options", response_model=ProjectOptionListResponse)
async def list_report_project_options(
    current_user: CurrentUser,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectOptionListResponse:
    projects, total = await ProjectService(session).list_report_project_options(
        current_user, search=search, limit=limit, offset=offset
    )
    return ProjectOptionListResponse(
        items=[ProjectOption.model_validate(project) for project in projects], total=total
    )


@router.get("", response_model=DailyReportListResponse)
async def list_reports(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DailyReportListResponse:
    reports, total = await ReportService(session).list_reports(
        actor=current_user,
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return DailyReportListResponse(
        items=[DailyReportResponse.model_validate(report) for report in reports],
        total=total,
    )


@router.post("", response_model=DailyReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    payload: DailyReportCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    offline_owner: Annotated[
        UUID | None,
        Header(alias="X-Offline-Owner", description="Required for local-* Idempotency-Key values."),
    ] = None,
) -> DailyReportResponse:
    key = validate_key(idempotency_key)
    if key and key.startswith("local-") and offline_owner is None:
        raise AppException(
            "Reload the portal before saving this offline draft.",
            status_code=409,
            error_code="OFFLINE_REPORT_CLIENT_UPGRADE_REQUIRED",
        )
    if offline_owner is not None and offline_owner != current_user.id:
        raise AppException(
            "The offline draft belongs to another account.",
            status_code=403,
            error_code="OFFLINE_REPORT_OWNER_MISMATCH",
        )
    report = await ReportService(session).create_report(
        payload,
        current_user,
        idempotency_key=key,
    )
    return DailyReportResponse.model_validate(report)


@router.get("/{report_id}", response_model=DailyReportResponse)
async def get_report(
    report_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).get_report(report_id, current_user)
    return DailyReportResponse.model_validate(report)


@router.get("/{report_id}/pdf")
async def download_report_pdf(
    report_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> Response:
    export, pdf_bytes = await ReportExportService(session).get_or_create_pdf(
        report_id,
        current_user,
    )
    return Response(
        content=pdf_bytes,
        media_type=PDF_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{export.file_name}"'},
    )


@router.get("/{report_id}/supervisor-updates", response_model=list[SupervisorUpdateResponse])
async def list_report_supervisor_updates(
    report_id: UUID, current_user: CurrentUser, session: DbSession
) -> list[SupervisorUpdateResponse]:
    updates = await ReportService(session).list_supervisor_evidence(report_id, current_user)
    return await ReportingService(session).describe_updates(updates)


@router.put("/{report_id}", response_model=DailyReportResponse)
async def update_report(
    report_id: UUID,
    payload: DailyReportUpdateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).update_report(report_id, payload, current_user)
    return DailyReportResponse.model_validate(report)


@router.post("/{report_id}/submit", response_model=DailyReportResponse)
async def submit_report(
    report_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).submit_report(report_id, current_user)
    return DailyReportResponse.model_validate(report)


@router.post("/{report_id}/approve", response_model=DailyReportResponse)
async def approve_report(
    report_id: UUID,
    payload: DailyReportDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).approve_report(
        report_id,
        current_user,
        comments=payload.comments,
        target_covered=payload.target_covered,
    )
    return DailyReportResponse.model_validate(report)


@router.post("/{report_id}/reject", response_model=DailyReportResponse)
async def reject_report(
    report_id: UUID,
    payload: DailyReportDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).reject_report(
        report_id,
        current_user,
        comments=payload.comments,
    )
    return DailyReportResponse.model_validate(report)


@router.post("/{report_id}/override", response_model=DailyReportResponse)
async def override_report(
    report_id: UUID,
    payload: DailyReportOverrideRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> DailyReportResponse:
    report = await ReportService(session).override_report(
        report_id,
        current_user,
        decision=payload.decision,
        reason=payload.reason,
        target_covered=payload.target_covered,
    )
    return DailyReportResponse.model_validate(report)
