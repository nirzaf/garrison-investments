from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.audit import AuditLogListResponse, AuditLogResponse
from app.services.audit_service import AuditService
from app.utils.permissions import PERMISSION_AUDIT_VIEW

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])

CanViewAudit = Annotated[User, Depends(require_permission(PERMISSION_AUDIT_VIEW))]


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    _: CanViewAudit,
    session: DbSession,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    user_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditLogListResponse:
    logs, total = await AuditService(session).list_logs(
        action=action,
        entity_type=entity_type,
        user_id=user_id,
        search=search,
        limit=limit,
        offset=offset,
    )
    return AuditLogListResponse(
        items=[AuditLogResponse.model_validate(log) for log in logs],
        total=total,
    )
