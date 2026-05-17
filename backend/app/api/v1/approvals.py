from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.approvals import (
    ApprovalCreateRequest,
    ApprovalDecisionRequest,
    ApprovalDelegationRequest,
    ApprovalListResponse,
    ApprovalOverrideRequest,
    ApprovalResponse,
)
from app.services.approval_service import ENTITY_BACKED_REQUEST_TYPES, ApprovalService
from app.utils.exceptions import AppException

router = APIRouter(prefix="/approvals", tags=["Approvals"])


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    current_user: CurrentUser,
    session: DbSession,
    box: Annotated[str, Query(pattern="^(inbox|outbox)$")] = "inbox",
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ApprovalListResponse:
    approvals, total = await ApprovalService(session).list_for_user(
        actor=current_user,
        box=box,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return ApprovalListResponse(
        items=[ApprovalResponse.model_validate(approval) for approval in approvals],
        total=total,
    )


@router.post("", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    payload: ApprovalCreateRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    # Entity-backed approvals are opened by their owning services with internal=True.
    if payload.request_type in ENTITY_BACKED_REQUEST_TYPES:
        raise AppException(
            "This approval type must be created by its owning workflow.",
            status_code=403,
            error_code="APPROVAL_TYPE_FORBIDDEN",
        )
    approval = await ApprovalService(session).create_approval(payload, current_user)
    return ApprovalResponse.model_validate(approval)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    approval = await ApprovalService(session).get_for_actor(approval_id, current_user)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    approval = await ApprovalService(session).approve(approval_id, current_user, payload.comments)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject(
    approval_id: UUID,
    payload: ApprovalDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    approval = await ApprovalService(session).reject(approval_id, current_user, payload.comments)
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/delegate", response_model=ApprovalResponse)
async def delegate(
    approval_id: UUID,
    payload: ApprovalDelegationRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    approval = await ApprovalService(session).delegate(
        approval_id,
        current_user,
        payload.delegated_to_id,
        payload.reason,
    )
    return ApprovalResponse.model_validate(approval)


@router.post("/{approval_id}/override", response_model=ApprovalResponse)
async def override(
    approval_id: UUID,
    payload: ApprovalOverrideRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> ApprovalResponse:
    approval = await ApprovalService(session).override(
        approval_id,
        current_user,
        payload.decision,
        payload.reason,
    )
    return ApprovalResponse.model_validate(approval)
