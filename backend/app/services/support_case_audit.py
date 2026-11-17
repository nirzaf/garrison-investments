from asyncio import timeout
from datetime import timedelta
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_business_actions import (
    SupportBusinessAction,
    SupportBusinessApproval,
    SupportBusinessEvent,
)
from app.models.support_case_actions import SupportCaseAction, SupportCaseActionEvent
from app.models.support_case_audit import SupportCaseAuditRead
from app.models.support_cases import (
    SupportCase,
    SupportCaseEvent,
    SupportCaseMember,
    SupportLogRead,
    SupportOperatorGrant,
)
from app.models.support_directory import SupportDirectoryRead
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now

Family = Literal["case", "case_decision", "account_decision", "directory", "runtime"]


class SupportAuditQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime
    ended_at: AwareDatetime
    limit: int = Field(default=25, ge=1, le=100)

    @model_validator(mode="after")
    def check_window(self) -> Self:
        if not timedelta(0) < self.ended_at - self.started_at <= timedelta(hours=24):
            raise ValueError("Select a positive window of at most 24 hours.")
        return self


class SupportAuditEvent(BaseModel):
    reference_id: UUID
    operator_id: UUID
    occurred_at: AwareDatetime
    family: Family
    event: str


class SupportAuditPage(BaseModel):
    events: list[SupportAuditEvent]
    truncated: bool


async def read_case_audit(
    session: AsyncSession,
    token: str | None,
    case_id: UUID,
    query: SupportAuditQuery,
    request_id: str,
) -> SupportAuditPage:
    operator, active = await SupportIdentity(session).current(token)
    grant = await session.get(
        SupportOperatorGrant, (operator.id, "logs.audit"), with_for_update=True
    )
    if grant is None:
        raise PermissionDeniedException("logs.audit")
    case = await session.get(SupportCase, case_id, with_for_update=True)
    if (
        case is None
        or await session.get(SupportCaseMember, (case_id, operator.id), with_for_update=True)
        is None
    ):
        raise NotFoundException("Support case audit")
    recent = await session.scalar(
        select(func.count())
        .select_from(SupportCaseAuditRead)
        .where(
            SupportCaseAuditRead.operator_id == operator.id,
            SupportCaseAuditRead.occurred_at > utc_now() - timedelta(minutes=1),
        )
    )
    if recent is not None and recent >= 20:
        raise AppException(
            "Wait before reading more case audit events.",
            status_code=429,
            error_code="SUPPORT_AUDIT_LIMIT",
        )

    case_events = select(
        SupportCaseEvent.id.label("reference_id"),
        SupportCaseEvent.operator_id,
        SupportCaseEvent.occurred_at,
        literal("case").label("family"),
        SupportCaseEvent.action.label("event"),
    ).where(SupportCaseEvent.case_id == case_id)
    decisions = (
        select(
            SupportCaseActionEvent.id,
            SupportCaseActionEvent.actor_id,
            SupportCaseActionEvent.occurred_at,
            literal("case_decision"),
            SupportCaseActionEvent.event,
        )
        .join(SupportCaseAction)
        .where(SupportCaseAction.case_id == case_id)
    )
    business = (
        select(
            SupportBusinessEvent.id,
            SupportBusinessEvent.actor_id,
            SupportBusinessEvent.occurred_at,
            literal("account_decision"),
            SupportBusinessEvent.event,
        )
        .join(SupportBusinessAction)
        .where(SupportBusinessAction.case_id == case_id)
    )
    approvals = (
        select(
            SupportBusinessApproval.action_id,
            SupportBusinessApproval.reviewer_id,
            SupportBusinessApproval.occurred_at,
            literal("account_decision"),
            literal("reviewed"),
        )
        .join(SupportBusinessAction)
        .where(SupportBusinessAction.case_id == case_id)
    )
    directory = select(
        SupportDirectoryRead.id,
        SupportDirectoryRead.operator_id,
        SupportDirectoryRead.occurred_at,
        literal("directory"),
        literal("read"),
    ).where(SupportDirectoryRead.case_id == case_id)
    runtime = select(
        SupportLogRead.id,
        SupportLogRead.operator_id,
        SupportLogRead.occurred_at,
        literal("runtime"),
        literal("read"),
    ).where(SupportLogRead.case_id == case_id)
    events = union_all(case_events, decisions, business, approvals, directory, runtime).subquery()
    statement = (
        select(events)
        .where(events.c.occurred_at >= query.started_at, events.c.occurred_at < query.ended_at)
        .order_by(
            events.c.occurred_at.desc(), events.c.reference_id.desc(), events.c.operator_id.desc()
        )
        .limit(query.limit + 1)
    )
    try:
        async with timeout(5):
            rows = (await session.execute(statement)).mappings().all()
    except TimeoutError as exc:
        raise AppException(
            "Case audit is temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_AUDIT_TIMEOUT",
        ) from exc
    result = SupportAuditPage(
        events=[SupportAuditEvent.model_validate(row) for row in rows[: query.limit]],
        truncated=len(rows) > query.limit,
    )
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    session.add(
        SupportCaseAuditRead(
            id=uuid4(),
            case_id=case.id,
            operator_id=operator.id,
            request_id=request_id,
            occurred_at=now,
            started_at=query.started_at,
            ended_at=query.ended_at,
            event_count=len(result.events),
        )
    )
    active.last_seen_at = now
    await session.commit()
    return result
