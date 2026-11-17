import json
from datetime import timedelta
from secrets import token_bytes
from typing import Literal
from uuid import UUID, uuid4

import cbor2
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import generate_registration_options, options_to_json, verify_registration_response
from webauthn.helpers import parse_registration_credential_json
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    CredentialDeviceType,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.models.support_custody import SupportCustodyAction, SupportCustodyEvent
from app.models.support_identity import SupportCredential, SupportOperator
from app.models.support_registration import SupportBootstrap, SupportRegistration
from app.services.support_bootstrap import (
    BOOTSTRAP_ID,
    finish_first_custodian_registration,
    record_bootstrap_event,
)
from app.services.support_custody import _CUSTODY_LOCK, SupportCustody
from app.services.support_identity import SUPPORT_HOST, SUPPORT_ORIGIN, _digest
from app.utils.exceptions import AppException
from app.utils.security import utc_now

_ALGORITHMS = [COSEAlgorithmIdentifier.ECDSA_SHA_256]
RegistrationState = Literal["pending", "registered", "activated"]


def _denied() -> AppException:
    return AppException(
        "Support passkey registration could not be verified.",
        status_code=403,
        error_code="SUPPORT_REGISTRATION_DENIED",
    )


class SupportRegistrationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _load(
        self, token: str, *, include_consumed: bool = False
    ) -> tuple[SupportRegistration, SupportCustodyAction | SupportBootstrap, SupportOperator]:
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        invitation = await self.session.scalar(
            select(SupportRegistration)
            .where(SupportRegistration.invitation_hash == _digest(token))
            .with_for_update()
        )
        if invitation is None or invitation.expires_at <= utc_now():
            raise _denied()
        consumed = invitation.consumed_at is not None
        if consumed and not include_consumed:
            raise _denied()
        if invitation.bootstrap_operator_id is not None:
            entry = await self.session.get(SupportBootstrap, BOOTSTRAP_ID, with_for_update=True)
            if (
                entry is None or (entry.activated_at is not None and not consumed)
                or invitation.bootstrap_operator_id not in {entry.first_id, entry.second_id}
            ):
                raise _denied()
            operator = await self.session.get(
                SupportOperator, invitation.bootstrap_operator_id, with_for_update=True
            )
            expected_status = "active" if entry.activated_at is not None else "pending"
            if (
                operator is None or operator.status != expected_status
                or operator.grant_epoch != invitation.grant_epoch
            ):
                raise _denied()
            return invitation, entry, operator
        proposal = await self.session.get(SupportCustodyAction, invitation.custody_action_id)
        if (
            proposal is None
            or not proposal.executed_at
            or proposal.kind not in {"enroll", "recover"}
        ):
            raise _denied()
        operator = await self.session.get(SupportOperator, proposal.target_id, with_for_update=True)
        expected_status = "pending" if proposal.kind == "enroll" else "suspended"
        eligible_statuses = {expected_status, "active"} if consumed else {expected_status}
        if (
            operator is None
            or operator.status not in eligible_statuses
            or operator.grant_epoch != invitation.grant_epoch
        ):
            raise _denied()
        if consumed:
            return invitation, proposal, operator
        for operator_id, epoch in (
            (proposal.requester_id, proposal.requester_epoch),
            (proposal.reviewer_id, proposal.reviewer_epoch),
        ):
            if (
                not operator_id
                or not epoch
                or await self.session.scalar(
                    SupportCustody.usable_custodians().where(
                        SupportOperator.id == operator_id, SupportOperator.grant_epoch == epoch
                    )
                )
                is None
            ):
                raise _denied()
        return invitation, proposal, operator

    async def status(self, token: str) -> tuple[UUID, RegistrationState]:
        invitation, _, operator = await self._load(token, include_consumed=True)
        if invitation.consumed_at is None:
            return operator.id, "pending"
        return operator.id, "activated" if operator.status == "active" else "registered"

    async def options(self, token: str) -> str:
        invitation, _, operator = await self._load(token)
        now = utc_now()
        if invitation.challenge is None or (
            invitation.challenge_expires_at and invitation.challenge_expires_at <= now
        ):
            invitation.challenge = token_bytes(32)
            invitation.challenge_expires_at = min(now + timedelta(minutes=2), invitation.expires_at)
        options = generate_registration_options(
            rp_id=SUPPORT_HOST,
            rp_name="Garrisons Support",
            user_id=operator.id.bytes,
            user_name=str(operator.id),
            user_display_name="Garrisons support operator",
            challenge=invitation.challenge,
            timeout=120_000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                require_resident_key=True,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            supported_pub_key_algs=_ALGORITHMS,
        )
        await self.session.commit()
        return options_to_json(options)

    def _audit(
        self,
        proposal: SupportCustodyAction | SupportBootstrap,
        operator: SupportOperator,
        action: str,
        request_id: str,
    ) -> None:
        if isinstance(proposal, SupportBootstrap):
            record_bootstrap_event(self.session, action, request_id, operator.id)
            return
        self.session.add(
            SupportCustodyEvent(
                id=uuid4(),
                custody_action_id=proposal.id,
                actor_id=operator.id,
                action=action,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    async def register(
        self, token: str, response: dict[str, object], request_id: str
    ) -> tuple[bool, bool]:
        invitation, proposal, operator = await self._load(token)
        now = utc_now()
        if (
            invitation.challenge is None
            or invitation.challenge_expires_at is None
            or invitation.challenge_expires_at <= now
        ):
            raise _denied()
        challenge = invitation.challenge
        invitation.challenge = None
        invitation.challenge_expires_at = None
        try:
            credential = parse_registration_credential_json(response)
            client_data = json.loads(credential.response.client_data_json)
            if (
                not isinstance(client_data, dict)
                or client_data.get("crossOrigin", False) is not False
            ):
                raise _denied()
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=SUPPORT_HOST,
                expected_origin=SUPPORT_ORIGIN,
                supported_pub_key_algs=_ALGORITHMS,
                require_user_verification=True,
            )
            if verified.credential_device_type != CredentialDeviceType.SINGLE_DEVICE:
                raise _denied()
            public_key = cbor2.dumps(cbor2.loads(verified.credential_public_key), canonical=True)
            operator_ids = (
                (proposal.first_id, proposal.second_id)
                if isinstance(proposal, SupportBootstrap) else (operator.id,)
            )
            prior_keys = await self.session.scalars(
                select(SupportCredential.public_key).where(
                    SupportCredential.operator_id.in_(operator_ids)
                )
            )
            if any(
                cbor2.dumps(cbor2.loads(key), canonical=True) == public_key for key in prior_keys
            ):
                raise _denied()
            if invitation.expires_at <= utc_now():
                raise _denied()
            inserted = await self.session.scalar(
                insert(SupportCredential)
                .values(
                    id=uuid4(),
                    operator_id=operator.id,
                    credential_hash=_digest(verified.credential_id),
                    public_key=public_key,
                    sign_count=verified.sign_count,
                )
                .on_conflict_do_nothing(index_elements=[SupportCredential.credential_hash])
                .returning(SupportCredential.id)
            )
            if inserted is None:
                raise _denied()
        except (WebAuthnException, ValueError, AppException) as exc:
            self._audit(proposal, operator, "registration_denied", request_id)
            await self.session.commit()
            raise _denied() from exc
        invitation.consumed_at = utc_now()
        if isinstance(proposal, SupportBootstrap):
            outcome = await finish_first_custodian_registration(
                self.session, proposal, operator.id, request_id
            )
            await self.session.commit()
            return outcome
        self._audit(proposal, operator, "passkey_added", request_id)
        count = await self.session.scalar(
            select(func.count())
            .select_from(SupportCredential)
            .where(
                SupportCredential.operator_id == operator.id, SupportCredential.revoked_at.is_(None)
            )
        )
        activated = count == 2
        if activated:
            operator.status = "active"
            self._audit(proposal, operator, "operator_activated", request_id)
        await self.session.commit()
        return activated, False
