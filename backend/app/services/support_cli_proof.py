from base64 import urlsafe_b64decode
from dataclasses import dataclass
from hmac import compare_digest
from typing import cast
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.support_business_actions import SupportBusinessAction, SupportBusinessProof
from app.models.support_case_actions import SupportCaseAction, SupportCaseActionProof
from app.models.support_cli_proof import SupportCliProof
from app.models.support_custody import SupportCustodyAction, SupportCustodyProof
from app.models.support_evidence_export import SupportEvidenceExport, SupportEvidenceProof
from app.models.support_identity import SupportOperator, SupportSession
from app.services.support_identity import SupportIdentity, _digest, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException
from app.utils.security import utc_now

ActionProof = (
    SupportCaseActionProof | SupportBusinessProof | SupportCustodyProof | SupportEvidenceProof
)
Action = SupportCaseAction | SupportBusinessAction | SupportCustodyAction | SupportEvidenceExport


@dataclass(frozen=True)
class ProofDisplay:
    operation: str
    stage: str
    action_id: UUID


class SupportCliProofs:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _authenticated(self, token: str | None, csrf: str | None) -> SupportSession:
        _, active = await SupportIdentity(self.session).current(token)
        if not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf)):
            raise AppException("The support request could not be verified.", status_code=403)
        return active

    async def _proof(self, proof_id: UUID, session_id: UUID) -> tuple[ActionProof, ProofDisplay]:
        kinds: tuple[tuple[type[ActionProof], type[Action]], ...] = (
            (SupportCaseActionProof, SupportCaseAction),
            (SupportBusinessProof, SupportBusinessAction),
            (SupportCustodyProof, SupportCustodyAction),
            (SupportEvidenceProof, SupportEvidenceExport),
        )
        for proof_model, action_model in kinds:
            proof = cast(ActionProof | None, await self.session.get(proof_model, proof_id))
            if not proof:
                continue
            if proof.session_id != session_id or proof.consumed_at or proof.expires_at <= utc_now():
                break
            if isinstance(proof, SupportCustodyProof):
                action_id = proof.custody_action_id
                stage = proof.stage
            elif isinstance(proof, (SupportBusinessProof, SupportEvidenceProof)):
                action_id, stage = proof.action_id, proof.stage
            else:
                action_id, stage = proof.action_id, "apply"
            action = cast(Action | None, await self.session.get(action_model, action_id))
            if action is not None:
                return proof, ProofDisplay(
                    operation="evidence_export" if isinstance(action, SupportEvidenceExport)
                    else action.kind,
                    stage=stage,
                    action_id=action_id,
                )
            break
        raise NotFoundException("CLI passkey handoff")

    async def start(
        self,
        token: str | None,
        csrf: str | None,
        proof_id: UUID,
        pairing_hash: str,
        public_key: str,
    ) -> UUID:
        active = await self._authenticated(token, csrf)
        proof, _ = await self._proof(proof_id, active.id)
        try:
            key = load_der_public_key(urlsafe_b64decode(public_key + "=" * (-len(public_key) % 4)))
            if not isinstance(key, RSAPublicKey) or key.key_size != 2048:
                raise ValueError
        except ValueError:
            raise AppException("The CLI encryption key is invalid.", status_code=422) from None
        existing = await self.session.scalar(
            select(SupportCliProof.id).where(SupportCliProof.proof_id == proof_id)
        )
        if existing is not None:
            raise AppException("This proof already has a handoff.", status_code=409)
        handoff = SupportCliProof(
            id=uuid4(),
            proof_id=proof_id,
            session_id=active.id,
            pairing_hash=pairing_hash,
            public_key=public_key,
            expires_at=min(proof.expires_at, support_session_deadline(active)),
        )
        self.session.add(handoff)
        await self.session.commit()
        return handoff.id

    async def _paired(self, reference: UUID, code: str) -> SupportCliProof:
        handoff = await self.session.get(SupportCliProof, reference, with_for_update=True)
        if (
            handoff is None
            or handoff.expires_at <= utc_now()
            or handoff.taken_at
            or handoff.sealed is not None
            or not compare_digest(handoff.pairing_hash, _digest(code))
        ):
            raise NotFoundException("CLI passkey handoff")
        active = await self.session.get(SupportSession, handoff.session_id)
        if active is None or active.revoked_at or support_session_deadline(active) <= utc_now():
            raise NotFoundException("CLI passkey handoff")
        operator = await self.session.get(SupportOperator, active.operator_id)
        if (
            operator is None
            or operator.status != "active"
            or operator.grant_epoch != active.grant_epoch
        ):
            raise NotFoundException("CLI passkey handoff")
        return handoff

    async def options(
        self, reference: UUID, code: str
    ) -> tuple[SupportCliProof, str, ProofDisplay]:
        handoff = await self._paired(reference, code)
        proof, display = await self._proof(handoff.proof_id, handoff.session_id)
        options = SupportIdentity._public_key_options(proof.challenge)
        return handoff, options, display

    async def submit(self, reference: UUID, code: str, sealed: str) -> None:
        handoff = await self._paired(reference, code)
        await self._proof(handoff.proof_id, handoff.session_id)
        handoff.sealed = sealed
        await self.session.commit()

    async def take(self, token: str | None, csrf: str | None, reference: UUID) -> str:
        active = await self._authenticated(token, csrf)
        handoff = await self.session.get(SupportCliProof, reference, with_for_update=True)
        if (
            handoff is None
            or handoff.session_id != active.id
            or handoff.taken_at
            or handoff.expires_at <= utc_now()
        ):
            raise NotFoundException("CLI passkey handoff")
        await self._proof(handoff.proof_id, active.id)
        if handoff.sealed is None:
            raise AppException("The browser has not returned a passkey proof.", status_code=409)
        response = handoff.sealed
        handoff.sealed = None
        handoff.taken_at = utc_now()
        await self.session.commit()
        return response
