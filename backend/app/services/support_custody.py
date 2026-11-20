from datetime import timedelta
from hmac import compare_digest
from secrets import token_bytes, token_urlsafe
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import generate_authentication_options, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import UserVerificationRequirement

from app.models.support_cases import SupportOperatorGrant
from app.models.support_custody import (
    SupportCustodyAction,
    SupportCustodyEvent,
    SupportCustodyProof,
)
from app.models.support_identity import SupportCredential, SupportOperator, SupportSession
from app.models.support_registration import SupportRegistration
from app.services.support_identity import (
    SUPPORT_HOST,
    SupportIdentity,
    _digest,
    support_session_deadline,
)
from app.utils.exceptions import AppException
from app.utils.security import utc_now

Stage = Literal["review", "execute"]
RegistrationKind = Literal["enroll", "recover"]
Kind = Literal["suspend", "grant_change", "enroll", "recover"]
_REQUIRED_STATUS = {
    "suspend": "active",
    "grant_change": "active",
    "enroll": "pending",
    "recover": "suspended",
}
GrantCapability = Literal[
    "cases.manage",
    "logs.runtime",
    "logs.stream",
    "logs.export",
    "health.read",
    "directory.read",
    "account.request",
    "logs.audit",
    "simulation.start",
    "overview.company.read",
    "overview.projects.read",
    "overview.workforce.read",
    "overview.inventory.read",
    "overview.suppliers.read",
    "overview.documents.read",
    "overview.finance.read",
    "overview.approvals.read",
    "jobs.read",
    "backups.read",
    "config.read",
    "incidents.read",
    "company.directory.read",
    "company.accounts.manage",
    "company.access.assign",
    "company.sessions.read",
    "company.sessions.revoke",
    "company.settings.manage",
    "company.jobs.retry",
    "company.data.inspect",
]
_CUSTODY_CAPABILITY = "operator.manage"
_MIN_CUSTODIANS = 2
# Shared by every custody mutation. Acquire before any operator or session lock.
_CUSTODY_LOCK = 1_738_287_065


def _conflict(message: str = "The custody proposal is no longer actionable.") -> AppException:
    return AppException(message, status_code=409, error_code="SUPPORT_CUSTODY_CONFLICT")


def _forbidden() -> AppException:
    return AppException(
        "This operator cannot perform the custody action.",
        status_code=403,
        error_code="SUPPORT_CUSTODY_DENIED",
    )


class SupportCustody:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = SupportIdentity(session)

    @staticmethod
    def usable_custodians() -> Select[UUID]:
        credential_count = (
            select(func.count())
            .select_from(SupportCredential)
            .where(
                SupportCredential.operator_id == SupportOperator.id,
                SupportCredential.revoked_at.is_(None),
            )
            .correlate(SupportOperator)
            .scalar_subquery()
        )
        return (
            select(SupportOperator.id)
            .join(SupportOperatorGrant, SupportOperatorGrant.operator_id == SupportOperator.id)
            .where(
                SupportOperator.status == "active",
                SupportOperatorGrant.capability == _CUSTODY_CAPABILITY,
                credential_count >= 2,
            )
        )

    async def _actor(
        self, token: str | None, csrf: str | None
    ) -> tuple[SupportOperator, SupportSession]:
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        operator, active = await self.identity.current(token)
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise _forbidden()
        if (
            await self.session.scalar(
                self.usable_custodians().where(SupportOperator.id == operator.id)
            )
            is None
        ):
            raise _forbidden()
        return operator, active

    def _audit(
        self, proposal: SupportCustodyAction, actor: SupportOperator, action: str, request_id: str
    ) -> None:
        self.session.add(
            SupportCustodyEvent(
                id=uuid4(),
                custody_action_id=proposal.id,
                actor_id=actor.id,
                action=action,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    async def propose(
        self,
        token: str | None,
        csrf: str | None,
        target_id: UUID,
        request_id: str,
        *,
        capability: GrantCapability | None = None,
        enable: bool | None = None,
        registration_kind: RegistrationKind | None = None,
    ) -> SupportCustodyAction:
        actor, active = await self._actor(token, csrf)
        if actor.id == target_id:
            raise _forbidden()
        kind: Kind = registration_kind or ("grant_change" if capability is not None else "suspend")
        target = await self.session.get(SupportOperator, target_id, with_for_update=True)
        if target is None or target.status != _REQUIRED_STATUS[kind]:
            raise _conflict()
        if capability is not None:
            existing = await self.session.get(SupportOperatorGrant, (target_id, capability))
            if enable == (existing is not None):
                raise _conflict("The requested capability already has that state.")
        now = utc_now()
        proposal = SupportCustodyAction(
            id=uuid4(),
            kind=kind,
            capability=capability,
            enable=enable,
            target_id=target_id,
            requester_id=actor.id,
            target_epoch=target.grant_epoch,
            requester_epoch=actor.grant_epoch,
            expires_at=now + timedelta(minutes=15),
        )
        self.session.add(proposal)
        await self.session.flush()
        if support_session_deadline(active) <= utc_now():
            raise _forbidden()
        self._audit(proposal, actor, "proposed", request_id)
        await self.session.commit()
        return proposal

    async def _action(
        self, proposal_id: UUID, actor: SupportOperator, stage: Stage, kind: Kind
    ) -> tuple[SupportCustodyAction, SupportOperator]:
        proposal = await self.session.get(SupportCustodyAction, proposal_id, with_for_update=True)
        if (
            proposal is None
            or proposal.kind != kind
            or proposal.executed_at
            or proposal.expires_at <= utc_now()
        ):
            raise _conflict()
        if stage == "review":
            if actor.id in (proposal.requester_id, proposal.target_id):
                raise _forbidden()
            if proposal.reviewer_id is not None:
                raise _conflict()
        elif actor.id != proposal.requester_id:
            raise _forbidden()
        elif proposal.reviewer_id is None:
            raise _conflict()

        for operator_id, epoch in (
            (proposal.requester_id, proposal.requester_epoch),
            (proposal.reviewer_id, proposal.reviewer_epoch),
        ):
            if operator_id is None:
                continue
            if (
                await self.session.scalar(
                    self.usable_custodians().where(
                        SupportOperator.id == operator_id, SupportOperator.grant_epoch == epoch
                    )
                )
                is None
            ):
                raise _conflict()
        target = await self.session.get(SupportOperator, proposal.target_id, with_for_update=True)
        if (
            target is None
            or target.status != _REQUIRED_STATUS[kind]
            or target.grant_epoch != proposal.target_epoch
        ):
            raise _conflict()
        return proposal, target

    async def options(
        self,
        token: str | None,
        csrf: str | None,
        proposal_id: UUID,
        stage: Stage,
        *,
        kind: Kind = "suspend",
    ) -> tuple[UUID, str, SupportCustodyAction]:
        actor, active = await self._actor(token, csrf)
        proposal, _ = await self._action(proposal_id, actor, stage, kind)
        now = utc_now()
        proof = SupportCustodyProof(
            id=uuid4(),
            custody_action_id=proposal.id,
            session_id=active.id,
            stage=stage,
            challenge=token_bytes(32),
            expires_at=min(now + timedelta(minutes=2), support_session_deadline(active)),
        )
        if proof.expires_at <= now:
            raise _forbidden()
        self.session.add(proof)
        options = generate_authentication_options(
            rp_id=SUPPORT_HOST,
            challenge=proof.challenge,
            timeout=120_000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        await self.session.commit()
        return proof.id, options_to_json(options), proposal

    async def decide(
        self,
        token: str | None,
        csrf: str | None,
        proposal_id: UUID,
        stage: Stage,
        challenge_id: UUID,
        assertion: dict[str, object],
        request_id: str,
        *,
        kind: Kind = "suspend",
    ) -> tuple[str, str] | None:
        actor, active = await self._actor(token, csrf)
        proposal, target = await self._action(proposal_id, actor, stage, kind)
        proof = await self.session.get(SupportCustodyProof, challenge_id, with_for_update=True)
        now = utc_now()
        if (
            proof is None
            or proof.custody_action_id != proposal.id
            or proof.session_id != active.id
            or proof.stage != stage
            or proof.consumed_at is not None
            or proof.expires_at <= now
        ):
            raise _conflict("A fresh passkey proof is required for this action.")
        proof.consumed_at = now
        try:
            await self.identity.verify_assertion(actor.id, proof.challenge, assertion)
        except (WebAuthnException, AppException, ValueError) as exc:
            self._audit(proposal, actor, "proof_denied", request_id)
            await self.session.commit()
            raise _forbidden() from exc
        now = utc_now()
        if min(support_session_deadline(active), proof.expires_at, proposal.expires_at) <= now:
            raise _conflict()
        invitations = None
        if stage == "review":
            proposal.reviewer_id = actor.id
            proposal.reviewer_epoch = actor.grant_epoch
            self._audit(proposal, actor, "reviewed", request_id)
        else:
            if kind == "suspend":
                custodians = set(await self.session.scalars(self.usable_custodians()))
                if target.id in custodians and len(custodians) <= _MIN_CUSTODIANS:
                    self._audit(proposal, actor, "floor_denied", request_id)
                    await self.session.commit()
                    raise _conflict("Suspension would leave fewer than two usable custodians.")
                target.status = "suspended"
            if kind in {"suspend", "enroll", "recover"}:
                await self.session.execute(
                    update(SupportCredential)
                    .where(
                        SupportCredential.operator_id == target.id,
                        SupportCredential.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
            elif kind == "grant_change":
                assert proposal.capability is not None and proposal.enable is not None
                existing = await self.session.get(
                    SupportOperatorGrant, (target.id, proposal.capability), with_for_update=True
                )
                if proposal.enable and existing is None:
                    self.session.add(
                        SupportOperatorGrant(operator_id=target.id, capability=proposal.capability)
                    )
                elif not proposal.enable and existing is not None:
                    await self.session.delete(existing)
                else:
                    raise _conflict("The target's capability changed before execution.")
            target.grant_epoch += 1
            await self.session.execute(
                update(SupportSession)
                .where(SupportSession.operator_id == target.id, SupportSession.revoked_at.is_(None))
                .values(revoked_at=now)
            )
            if kind in {"enroll", "recover"}:
                invitations = (token_urlsafe(32), token_urlsafe(32))
                self.session.add_all(
                    [
                        SupportRegistration(
                            id=uuid4(),
                            custody_action_id=proposal.id,
                            invitation_hash=_digest(value),
                            grant_epoch=target.grant_epoch,
                            expires_at=now + timedelta(minutes=10),
                        )
                        for value in invitations
                    ]
                )
            proposal.executed_at = now
            self._audit(proposal, actor, "executed", request_id)
        await self.session.commit()
        return invitations
