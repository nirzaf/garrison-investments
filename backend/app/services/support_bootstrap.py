from datetime import timedelta
from hmac import compare_digest
from secrets import token_urlsafe
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_cases import SupportOperatorGrant
from app.models.support_identity import SupportCredential, SupportOperator
from app.models.support_oversight import ALL_SUPPORT_CAPABILITIES
from app.models.support_registration import (
    SupportBootstrap,
    SupportBootstrapEvent,
    SupportRegistration,
)
from app.services.support_custody import _CUSTODY_LOCK
from app.services.support_identity import _digest
from app.utils.security import utc_now

BOOTSTRAP_ID = 1
SINGLE_OWNER_BOOTSTRAP_CAPABILITIES = (*ALL_SUPPORT_CAPABILITIES, "company.directory.read")
_DEVICES_PER_CUSTODIAN = 2


def record_bootstrap_event(
    session: AsyncSession, action: str, request_id: str, operator_id: UUID | None = None
) -> None:
    session.add(
        SupportBootstrapEvent(
            id=uuid4(),
            bootstrap_id=BOOTSTRAP_ID,
            operator_id=operator_id,
            action=action,
            request_id=request_id,
            occurred_at=utc_now(),
        )
    )


async def _device_count(session: AsyncSession, operator_id: UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(SupportCredential)
            .where(
                SupportCredential.operator_id == operator_id, SupportCredential.revoked_at.is_(None)
            )
        )
        or 0
    )


async def issue_first_custodian_invitations(
    session: AsyncSession, *, approval_digest: str, reissue: bool, single_owner: bool = False
) -> dict[UUID, list[str]]:
    """Issue or replace pending invitations under the same reviewed ceremony."""
    await session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
    entry = await session.get(SupportBootstrap, BOOTSTRAP_ID)
    request_id = str(uuid4())
    now = utc_now()
    if entry is None:
        existing = await session.scalar(select(SupportOperator.id).limit(1))
        if reissue or existing is not None:
            raise ValueError("Initial enrollment requires an empty technical operator registry.")
        first, second = uuid4(), None if single_owner else uuid4()
        session.add(
            SupportOperator(
                id=first,
                display_label="Sole owner" if single_owner else "First custodian",
                status="pending",
                grant_epoch=1,
            )
        )
        if second is not None:
            session.add(
                SupportOperator(
                    id=second, display_label="Second custodian", status="pending", grant_epoch=1
                )
            )
        await session.flush()
        entry = SupportBootstrap(
            id=BOOTSTRAP_ID,
            first_id=first,
            second_id=second,
            custody_mode="single_owner" if single_owner else "paired",
            approval_digest=approval_digest,
            started_at=now,
        )
        session.add(entry)
        await session.flush()
        record_bootstrap_event(session, "started", request_id)
    elif (
        not reissue
        or (entry.custody_mode == "single_owner") != single_owner
        or entry.activated_at
        or not compare_digest(entry.approval_digest, approval_digest)
    ):
        raise ValueError("The initial custody ceremony already exists or has completed.")

    result = {}
    for operator_id in entry.operator_ids:
        operator = await session.get(SupportOperator, operator_id, with_for_update=True)
        if operator is None or operator.status != "pending":
            raise ValueError("The approved custodian registry changed.")
        await session.execute(
            update(SupportRegistration)
            .where(
                SupportRegistration.bootstrap_operator_id == operator_id,
                SupportRegistration.consumed_at.is_(None),
                SupportRegistration.expires_at > now,
            )
            .values(expires_at=now)
        )
        remaining = _DEVICES_PER_CUSTODIAN - await _device_count(session, operator_id)
        if not 0 <= remaining <= _DEVICES_PER_CUSTODIAN:
            raise ValueError("The approved device count is inconsistent.")
        tokens = [token_urlsafe(32) for _ in range(remaining)]
        for token in tokens:
            session.add(
                SupportRegistration(
                    id=uuid4(),
                    bootstrap_operator_id=operator_id,
                    invitation_hash=_digest(token),
                    grant_epoch=operator.grant_epoch,
                    expires_at=now + timedelta(minutes=10),
                )
            )
        if tokens:
            record_bootstrap_event(session, "invitations_issued", request_id, operator_id)
        result[operator_id] = tokens
    return result


async def finish_first_custodian_registration(
    session: AsyncSession, entry: SupportBootstrap, operator_id: UUID, request_id: str
) -> tuple[bool, bool]:
    record_bootstrap_event(session, "passkey_added", request_id, operator_id)
    ids = entry.operator_ids
    counts = {identity: await _device_count(session, identity) for identity in ids}
    if set(counts.values()) != {_DEVICES_PER_CUSTODIAN}:
        return False, counts[operator_id] == _DEVICES_PER_CUSTODIAN
    for identity in ids:
        operator = await session.get(SupportOperator, identity, with_for_update=True)
        if operator is None or operator.status != "pending":
            raise ValueError("The approved custodian registry changed.")
        operator.status = "active"
        capabilities = (
            SINGLE_OWNER_BOOTSTRAP_CAPABILITIES
            if entry.custody_mode == "single_owner"
            else ("operator.manage",)
        )
        session.add_all(
            SupportOperatorGrant(operator_id=identity, capability=capability)
            for capability in capabilities
        )
        record_bootstrap_event(session, "activated", request_id, identity)
    entry.activated_at = utc_now()
    return True, False
