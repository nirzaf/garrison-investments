"""A minimal projection of one reviewed request attributed to the case subject."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog
from app.models.support_case_actions import SupportCaseAction
from app.models.support_cases import SupportCaseRequest
from app.services.support_request_logs import SUPPORT_REQUEST_ID
from app.utils.exceptions import NotFoundException

_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


class RequestSummary(BaseModel):
    request_ref: str
    method: str
    status_code: int
    occurred_at: datetime


async def read_linked_request_summary(
    session: AsyncSession, case_id: UUID, subject_id: UUID, event_id: UUID | None
) -> RequestSummary:
    if event_id is None:
        raise NotFoundException("Support request summary")
    row = (
        await session.execute(
            select(
                ActivityLog.request_id, ActivityLog.http_method,
                ActivityLog.status_code, ActivityLog.created_at,
            )
            .select_from(ActivityLog)
            .join(
                SupportCaseRequest,
                and_(
                    SupportCaseRequest.case_id == case_id,
                    SupportCaseRequest.request_id == ActivityLog.request_id,
                ),
            )
            .where(
                ActivityLog.id == event_id,
                ActivityLog.user_id == subject_id,
                ActivityLog.entity_type == "request",
                ActivityLog.action == "http.request",
                ActivityLog.deleted_at.is_(None),
                ActivityLog.http_method.in_(_METHODS),
                ActivityLog.status_code.between(100, 599),
                select(SupportCaseAction.id).where(
                    SupportCaseAction.case_id == case_id,
                    SupportCaseAction.kind == "evidence_link",
                    SupportCaseAction.source_event_id == event_id,
                    SupportCaseAction.source_request_id == ActivityLog.request_id,
                    SupportCaseAction.applied_at.is_not(None),
                ).correlate(ActivityLog).exists(),
            )
        )
    ).one_or_none()
    if (
        row is None or row.request_id is None or not SUPPORT_REQUEST_ID.fullmatch(row.request_id)
        or row.http_method is None or row.status_code is None
    ):
        raise NotFoundException("Support request summary")
    return RequestSummary(
        request_ref=row.request_id,
        method=row.http_method,
        status_code=row.status_code,
        occurred_at=row.created_at,
    )
