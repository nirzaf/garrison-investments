from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_case_actions import SupportCaseAction
from app.models.support_cases import (
    SupportCase,
    SupportCaseEvent,
    SupportCaseMember,
    SupportOperatorGrant,
)
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now

_MAX_EVENTS = 25


class SupportTimelineEvent(BaseModel):
    id: UUID
    occurred_at: datetime
    kind: str
    revision: int
    status: str | None
    request_id: str | None = None
    request_status: int | None = None


class SupportTimelineRead(BaseModel):
    events: list[SupportTimelineEvent]
    truncated: bool


async def read_case_timeline(
    session: AsyncSession, token: str | None, case_id: UUID, request_id: str
) -> SupportTimelineRead:
    operator, active = await SupportIdentity(session).current(token)
    for capability in ("cases.manage", "logs.runtime"):
        if (
            await session.get(SupportOperatorGrant, (operator.id, capability), with_for_update=True)
            is None
        ):
            raise PermissionDeniedException(capability)
    case = await session.get(SupportCase, case_id, with_for_update=True)
    if (
        case is None
        or case.owner_id is None
        or await session.get(SupportCaseMember, (case.id, operator.id), with_for_update=True)
        is None
    ):
        raise NotFoundException("Support case")
    events = await session.scalars(
        select(SupportCaseEvent)
        .where(
            SupportCaseEvent.case_id == case.id,
            SupportCaseEvent.action.in_(("created", "transitioned")),
        )
        .order_by(SupportCaseEvent.occurred_at.desc(), SupportCaseEvent.id.desc())
        .limit(_MAX_EVENTS + 1)
    )
    results = [
        SupportTimelineEvent(
            id=event.id,
            occurred_at=event.occurred_at,
            revision=event.revision,
            kind=event.action,
            status=event.status,
        )
        for event in events
    ]
    decisions = (
        await session.execute(
            select(
                SupportCaseAction.id,
                SupportCaseAction.applied_at,
                SupportCaseAction.kind,
                SupportCaseAction.case_revision,
                SupportCaseAction.source_request_id,
                SupportCaseAction.source_status,
            )
            .where(SupportCaseAction.case_id == case.id, SupportCaseAction.applied_at.is_not(None))
            .order_by(SupportCaseAction.applied_at.desc(), SupportCaseAction.id.desc())
            .limit(_MAX_EVENTS + 1)
        )
    ).all()
    for action_id, decision_time, kind, revision, source_request_id, source_status in decisions:
        assert decision_time is not None
        results.append(
            SupportTimelineEvent(
                id=action_id,
                occurred_at=decision_time,
                kind=kind,
                revision=revision + 1,
                status="verified" if kind == "verify" else "closed" if kind == "close" else None,
                request_id=source_request_id,
                request_status=source_status,
            )
        )
    results.sort(key=lambda event: (event.occurred_at, event.id), reverse=True)
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    session.add(
        SupportCaseEvent(
            id=uuid4(),
            case_id=case.id,
            operator_id=operator.id,
            action="timeline_read",
            revision=case.revision,
            status=case.status,
            request_id=request_id,
            occurred_at=now,
        )
    )
    active.last_seen_at = now
    await session.commit()
    return SupportTimelineRead(events=results[:_MAX_EVENTS], truncated=len(results) > _MAX_EVENTS)
