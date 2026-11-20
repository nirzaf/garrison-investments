from base64 import urlsafe_b64decode, urlsafe_b64encode
from binascii import Error
from datetime import datetime, timedelta
from hmac import compare_digest, digest
from uuid import UUID, uuid4

from sqlalchemy import Select, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_cases import (
    SupportCase,
    SupportCaseEvent,
    SupportCaseMember,
    SupportOperatorGrant,
)
from app.models.support_identity import SupportOperator, SupportSession
from app.schemas.support_cases import (
    SupportCaseCreate,
    SupportCasePage,
    SupportCaseRead,
    SupportCaseTransition,
)
from app.services.support_identity import SupportIdentity, _digest, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.security import utc_now

_CASES_MANAGE = "cases.manage"
_NEXT_STATUS = {"open": "investigating", "investigating": "mitigated"}


def _sign_cursor(payload: bytes, token: str) -> bytes:
    return digest(token.encode(), b"support-case-list-v1:" + payload, "sha256")


def _cursor(case: SupportCase, token: str) -> str:
    expires = int((utc_now() + timedelta(minutes=5)).timestamp())
    payload = f"{case.created_at.isoformat()}|{case.id}|{expires}".encode()
    return urlsafe_b64encode(_sign_cursor(payload, token) + payload).decode()


def _read_cursor(cursor: str, token: str) -> tuple[datetime, UUID]:
    try:
        raw = urlsafe_b64decode(cursor)
        signature, payload = raw[:32], raw[32:]
        if not compare_digest(signature, _sign_cursor(payload, token)):
            raise ValueError
        timestamp, case_id, expires = payload.decode().split("|")
        if int(expires) <= utc_now().timestamp():
            raise ValueError
        return datetime.fromisoformat(timestamp), UUID(case_id)
    except (ValueError, Error) as exc:
        raise AppException(
            "The case list cursor is invalid or expired.",
            status_code=422,
            error_code="SUPPORT_CASE_CURSOR_INVALID",
        ) from exc


def _scope(operator_id: UUID) -> Select[SupportCase]:
    return (
        select(SupportCase)
        .join(SupportCaseMember, SupportCaseMember.case_id == SupportCase.id)
        .where(SupportCaseMember.operator_id == operator_id, SupportCase.owner_id.is_not(None))
        .with_for_update(of=(SupportCase, SupportCaseMember))
    )


class SupportCases:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _actor(
        self, token: str | None, csrf: str | None = None, *, write: bool = False
    ) -> tuple[SupportOperator, SupportSession]:
        operator, active = await SupportIdentity(self.session).current(
            token, require_passkey_assurance=write
        )
        if write and (
            not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf))
        ):
            raise AppException(
                "Support request could not be verified.",
                status_code=403,
                error_code="SUPPORT_CSRF_INVALID",
            )
        grant = await self.session.get(
            SupportOperatorGrant, (operator.id, _CASES_MANAGE), with_for_update=True
        )
        if grant is None:
            raise PermissionDeniedException(_CASES_MANAGE)
        return operator, active

    def _audit(
        self,
        case: SupportCase,
        operator: SupportOperator,
        action: str,
        request_id: str,
        reason_code: str | None = None,
    ) -> None:
        self.session.add(
            SupportCaseEvent(
                id=uuid4(),
                case_id=case.id,
                operator_id=operator.id,
                action=action,
                revision=case.revision,
                status=case.status,
                reason_code=reason_code,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    async def _commit(self, active: SupportSession) -> None:
        await self.session.flush()
        now = utc_now()
        if support_session_deadline(active) <= now:
            raise AppException(
                "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
            )
        active.last_seen_at = now
        await self.session.commit()

    async def create(
        self, token: str | None, csrf: str | None, payload: SupportCaseCreate, request_id: str
    ) -> SupportCaseRead:
        operator, active = await self._actor(token, csrf, write=True)
        case = await self.session.scalar(
            insert(SupportCase)
            .values(
                id=uuid4(),
                owner_id=operator.id,
                external_ref=payload.external_ref,
                severity=payload.severity,
                reason_code=payload.reason_code,
                status="open",
            )
            .on_conflict_do_nothing(index_elements=[SupportCase.external_ref])
            .returning(SupportCase)
        )
        if case is None:
            raise AppException(
                "The case reference cannot be used.",
                status_code=409,
                error_code="SUPPORT_CASE_CONFLICT",
            )
        self.session.add(SupportCaseMember(case_id=case.id, operator_id=operator.id))
        self._audit(case, operator, "created", request_id, payload.reason_code)
        result = SupportCaseRead.model_validate(case)
        await self._commit(active)
        return result

    async def list(
        self, token: str | None, limit: int, cursor: str | None, request_id: str
    ) -> SupportCasePage:
        operator, active = await self._actor(token)
        assert token is not None  # Only an authenticated session reaches the cursor code.
        stmt = _scope(operator.id)
        if cursor:
            timestamp, case_id = _read_cursor(cursor, token)
            stmt = stmt.where(tuple_(SupportCase.created_at, SupportCase.id) < (timestamp, case_id))
        rows = list(
            await self.session.scalars(
                stmt.order_by(SupportCase.created_at.desc(), SupportCase.id.desc()).limit(limit + 1)
            )
        )
        visible = rows[:limit]
        for case in visible:
            self._audit(case, operator, "read", request_id)
        result = SupportCasePage(
            items=[SupportCaseRead.model_validate(case) for case in visible],
            next_cursor=_cursor(visible[-1], token) if len(rows) > limit else None,
        )
        await self._commit(active)
        return result

    async def _scoped_case(self, case_id: UUID, operator: SupportOperator) -> SupportCase:
        case = await self.session.scalar(_scope(operator.id).where(SupportCase.id == case_id))
        if case is None:
            raise NotFoundException("Support case")
        return case

    async def detail(self, token: str | None, case_id: UUID, request_id: str) -> SupportCaseRead:
        operator, active = await self._actor(token)
        case = await self._scoped_case(case_id, operator)
        self._audit(case, operator, "read", request_id)
        result = SupportCaseRead.model_validate(case)
        await self._commit(active)
        return result

    async def transition(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        revision: int,
        payload: SupportCaseTransition,
        request_id: str,
    ) -> SupportCaseRead:
        operator, active = await self._actor(token, csrf, write=True)
        case = await self._scoped_case(case_id, operator)
        if case.revision != revision or _NEXT_STATUS.get(case.status) != payload.status:
            raise AppException(
                "The case changed or this transition is unavailable.",
                status_code=409,
                error_code="SUPPORT_CASE_CONFLICT",
            )
        case.status = payload.status
        case.revision += 1
        case.updated_at = utc_now()
        self._audit(case, operator, "transitioned", request_id, payload.reason_code)
        result = SupportCaseRead.model_validate(case)
        await self._commit(active)
        return result
