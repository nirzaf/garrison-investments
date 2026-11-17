from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_cases import (
    SupportCase,
    SupportCaseMember,
    SupportCaseRequest,
    SupportLogRead,
    SupportOperatorGrant,
)
from app.models.support_identity import SupportSession
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.services.support_request_logs import (
    SupportRequestLogPage,
    SupportRequestLogQuery,
    project_request_logs,
)
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now

_LOGS_RUNTIME = "logs.runtime"


async def authorize_case_request_logs(
    session: AsyncSession,
    token: str | None,
    case_id: UUID,
    source_request_id: str,
    *,
    require_stream: bool = False,
) -> SupportSession:
    operator, auth_session = await SupportIdentity(session).current(token)
    await require_case_request_log_scope(
        session, operator.id, case_id, source_request_id,
        additional_grant="logs.stream" if require_stream else None,
    )
    return auth_session


async def require_case_request_log_scope(
    session: AsyncSession,
    operator_id: UUID,
    case_id: UUID,
    source_request_id: str,
    *,
    additional_grant: str | None,
) -> None:
    capabilities = (_LOGS_RUNTIME, additional_grant) if additional_grant else (_LOGS_RUNTIME,)
    for capability in capabilities:
        grant = await session.get(
            SupportOperatorGrant, (operator_id, capability), with_for_update=True
        )
        if grant is None:
            raise PermissionDeniedException(capability)
    case = await session.get(SupportCase, case_id, with_for_update=True)
    if case is None or case.status not in {"open", "investigating"}:
        raise NotFoundException("Support case evidence")
    if not await session.get(SupportCaseMember, (case_id, operator_id), with_for_update=True):
        raise NotFoundException("Support case evidence")
    if not await session.get(
        SupportCaseRequest, (case_id, source_request_id), with_for_update=True
    ):
        raise NotFoundException("Support case evidence")


async def read_case_request_logs(
    session: AsyncSession,
    token: str | None,
    case_id: UUID,
    query: SupportRequestLogQuery,
    request_id: str,
) -> SupportRequestLogPage:
    auth_session = await authorize_case_request_logs(session, token, case_id, query.request_id)
    now = utc_now()
    recent = await session.scalar(
        select(func.count())
        .select_from(SupportLogRead)
        .where(
            SupportLogRead.operator_id == auth_session.operator_id,
            SupportLogRead.occurred_at > now - timedelta(minutes=1),
        )
    )
    if recent is not None and recent >= 20:
        raise AppException(
            "Wait before searching support evidence again.",
            status_code=429,
            error_code="SUPPORT_LOG_RATE_LIMIT",
        )
    result = await project_request_logs(session, query)
    observed_at = utc_now()
    if support_session_deadline(auth_session) <= observed_at:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    session.add(
        SupportLogRead(
            id=uuid4(),
            operator_id=auth_session.operator_id,
            case_id=case_id,
            request_id=request_id,
            source_request_id=query.request_id,
            started_at=query.started_at,
            ended_at=query.ended_at,
            filter_status_code=query.status_code,
            requested_limit=query.limit,
            event_count=len(result.events),
            occurred_at=observed_at,
        )
    )
    auth_session.last_seen_at = observed_at
    await session.commit()
    return result
