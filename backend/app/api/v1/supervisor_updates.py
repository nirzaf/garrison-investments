from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.supervisor_updates import (
    SupervisorUpdateCreateRequest,
    SupervisorUpdateListResponse,
    SupervisorUpdateResponse,
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
) -> SupervisorUpdateListResponse:
    updates, total = await ReportingService(session).list_supervisor_updates(
        current_user=current_user,
        project_id=project_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return SupervisorUpdateListResponse(
        items=[SupervisorUpdateResponse.model_validate(update) for update in updates],
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


@router.post("/{update_id}/submit", response_model=SupervisorUpdateResponse)
async def submit_supervisor_update(
    update_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> SupervisorUpdateResponse:
    update = await ReportingService(session).submit_supervisor_update(update_id, current_user)
    return SupervisorUpdateResponse.model_validate(update)


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
