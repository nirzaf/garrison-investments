from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.supervisor_updates import (
    SupervisorUpdateCorrectionRequest,
    SupervisorUpdateCreateRequest,
    SupervisorUpdateDecisionRequest,
    SupervisorUpdateListResponse,
    SupervisorUpdateResponse,
    SupervisorUpdateSubmissionResponse,
    SupervisorUpdateSubmitRequest,
)
from app.services.reporting_service import ReportingService

router = APIRouter(prefix="/supervisor-updates", tags=["Supervisor Updates"])


@router.get("", response_model=SupervisorUpdateListResponse)
async def list_supervisor_updates(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    review_only: bool = False,
    update_id: UUID | None = None,
) -> SupervisorUpdateListResponse:
    service = ReportingService(session)
    updates, total = await service.list_supervisor_updates(
        current_user=current_user,
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
        review_only=review_only,
        update_id=update_id,
    )
    return SupervisorUpdateListResponse(
        items=await service.describe_updates(updates),
        total=total,
    )


@router.post("", response_model=SupervisorUpdateResponse, status_code=status.HTTP_201_CREATED)
async def create_supervisor_update(
    payload: SupervisorUpdateCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    update = await ReportingService(session).create_supervisor_update(payload, current_user)
    return SupervisorUpdateResponse.model_validate(update)


@router.post(
    "/{update_id}/correction", response_model=SupervisorUpdateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def correct_verified_supervisor_update(
    update_id: UUID,
    payload: SupervisorUpdateCorrectionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    update = await ReportingService(session).correct_verified_update(
        update_id, payload, current_user
    )
    return SupervisorUpdateResponse.model_validate(update)


@router.post("/{update_id}/submit", response_model=SupervisorUpdateResponse)
async def submit_supervisor_update(
    update_id: UUID,
    payload: SupervisorUpdateSubmitRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    service = ReportingService(session)
    update = await service.submit_supervisor_update(
        update_id, current_user, payload.expected_revision
    )
    return (await service.describe_updates([update]))[0]


@router.post("/{update_id}/review", response_model=SupervisorUpdateResponse)
async def review_supervisor_update(
    update_id: UUID,
    payload: SupervisorUpdateDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    service = ReportingService(session)
    update = await service.review_supervisor_update(update_id, payload, current_user)
    return (await service.describe_updates([update]))[0]


@router.get("/{update_id}/submissions", response_model=list[SupervisorUpdateSubmissionResponse])
async def supervisor_submission_history(
    update_id: UUID, current_user: CurrentUser, session: DbSession
) -> list[SupervisorUpdateSubmissionResponse]:
    history = await ReportingService(session).supervisor_submission_history(update_id, current_user)
    return [SupervisorUpdateSubmissionResponse.model_validate(row) for row in history]


@router.put("/{update_id}", response_model=SupervisorUpdateResponse)
async def update_supervisor_update(
    update_id: UUID,
    payload: SupervisorUpdateCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    update = await ReportingService(session).update_supervisor_update(
        update_id,
        payload,
        current_user,
    )
    return SupervisorUpdateResponse.model_validate(update)
