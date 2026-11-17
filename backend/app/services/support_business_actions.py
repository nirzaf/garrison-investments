import json
from datetime import timedelta
from hmac import compare_digest
from secrets import token_bytes
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only
from webauthn import generate_authentication_options, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import UserVerificationRequirement

from app.config import get_settings
from app.models.auth import AuthOtpChallenge
from app.models.support_business_actions import (
    SupportBusinessAction,
    SupportBusinessApproval,
    SupportBusinessContact,
    SupportBusinessEvent,
    SupportBusinessProof,
    SupportRecoveryDelivery,
)
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportCaseSubject
from app.models.support_identity import SupportOperator, SupportSession
from app.models.support_permission_view import SupportPermissionView, SupportPermissionViewEvent
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.schemas.support_business_actions import (
    BusinessActionCreate,
    BusinessActionRead,
    BusinessActionStage,
    RecoveryDeliveryState,
    RecoveryResetState,
    SupportRecoveryStatus,
)
from app.services.support_custody import _CUSTODY_LOCK, SupportCustody
from app.services.support_identity import (
    SUPPORT_HOST,
    SupportIdentity,
    _digest,
    support_session_deadline,
)
from app.services.support_project_projection import (
    PROJECT_VIEW_KINDS,
    MaskedProjects,
    masked_projects,
)
from app.services.support_request_projection import read_linked_request_summary
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    BUSINESS_ROLES,
    COMPANY_RESOURCE_ROLES,
    HR_PERMISSIONS,
    PROTECTED_USER_ROLES,
)
from app.utils.recovery_destination import (
    is_recovery_issuance_enabled,
    support_recovery_otp,
    support_recovery_otp_digest,
    verified_recovery_destination,
)
from app.utils.redaction import redact_text
from app.utils.security import utc_now

_CAPABILITY = "account.request"
_SIMULATION = "simulation.start"
_VIEW_KINDS = {"permission_view", "request_summary", "navigation_view"} | PROJECT_VIEW_KINDS


def _required_capability(kind: str) -> str:
    return _SIMULATION if kind in _VIEW_KINDS else _CAPABILITY


def _denied() -> AppException:
    return AppException(
        "This operator cannot perform the business account action.",
        status_code=403,
        error_code="SUPPORT_ACCOUNT_ACTION_DENIED",
    )


def _stale() -> AppException:
    return AppException(
        "The account action is unavailable, incomplete or stale.",
        status_code=409,
        error_code="SUPPORT_ACCOUNT_ACTION_STALE",
    )


def _recovery_binding(target: User) -> str:
    settings = get_settings()
    binding = verified_recovery_destination(
        settings, target.id, target.email, target.recovery_email_digest,
        target.recovery_email_verified_at,
    )
    if not is_recovery_issuance_enabled(settings, support_host=SUPPORT_HOST):
        raise _denied()
    if not target.is_active or binding is None:
        raise AppException(
            "The current recovery destination has not been verified.",
            status_code=409,
            error_code="SUPPORT_RECOVERY_DESTINATION_UNVERIFIED",
        )
    return binding


class SupportBusinessActions:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = SupportIdentity(session)
        self.users = UserRepository(session)

    async def _actor(
        self, token: str | None, csrf: str | None
    ) -> tuple[SupportOperator, SupportSession]:
        # Match business role/credential mutation order, then take technical custody.
        await self.users.lock_access_management()
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        actor, active = await self.identity.current(token)
        if (
            not csrf
            or len(csrf) != 43
            or not compare_digest(active.csrf_hash, _digest(csrf))
            or await self.session.scalar(
                select(SupportOperatorGrant.capability)
                .where(
                    SupportOperatorGrant.operator_id == actor.id,
                    SupportOperatorGrant.capability.in_((_CAPABILITY, _SIMULATION)),
                )
                .limit(1)
            )
            is None
        ):
            raise _denied()
        return actor, active

    async def _assigned(
        self, case_id: UUID, operator_id: UUID, epoch: int, capability: str = _CAPABILITY
    ) -> bool:
        operator = await self.session.get(SupportOperator, operator_id)
        return bool(
            operator is not None
            and operator.status == "active"
            and operator.grant_epoch == epoch
            and await self.session.get(SupportOperatorGrant, (operator_id, capability))
            and await self.session.get(SupportCaseMember, (case_id, operator_id))
        )

    async def _case(
        self, case_id: UUID, actor: SupportOperator
    ) -> tuple[SupportCase, SupportCaseSubject]:
        case = await self.session.get(SupportCase, case_id, with_for_update=True)
        if (
            case is None
            or case.status not in {"open", "investigating"}
            or await self.session.get(SupportCaseMember, (case_id, actor.id)) is None
        ):
            raise NotFoundException("Support account action")
        subject = await self.session.get(SupportCaseSubject, case.id, with_for_update=True)
        if subject is None:
            raise NotFoundException("Support account action")
        return case, subject

    async def _target(self, user_id: UUID, expected_revision: int, kind: str) -> User:
        user = (
            await self.users.lock_users(user_id, include_active_directors=kind == "disable")
        ).get(user_id)
        if user is None or user.role not in BUSINESS_ROLES:
            raise NotFoundException("Support account action")
        if user.access_revision != expected_revision or (
            kind in {"disable", "reactivate"} and user.is_active == (kind == "reactivate")
        ):
            raise _stale()
        return user

    def _audit(
        self, action: SupportBusinessAction, actor: SupportOperator, event: str, request_id: str
    ) -> None:
        self.session.add(
            SupportBusinessEvent(
                id=uuid4(),
                action_id=action.id,
                actor_id=actor.id,
                event=event,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    async def propose(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        key: UUID,
        payload: BusinessActionCreate,
        request_id: str,
    ) -> BusinessActionRead:
        actor, active = await self._actor(token, csrf)
        case, subject = await self._case(case_id, actor)
        if (
            payload.user_id != subject.user_id
            or await self.session.get(
                SupportOperatorGrant, (actor.id, _required_capability(payload.kind))
            )
            is None
        ):
            raise NotFoundException("Support account action")
        if payload.kind == "permission_view" and payload.permission_key not in (
            ALL_PERMISSIONS | HR_PERMISSIONS
        ):
            raise AppException("Choose a known business permission.", status_code=422)
        existing = await self.session.scalar(
            select(SupportBusinessAction).where(
                SupportBusinessAction.case_id == case.id,
                SupportBusinessAction.requester_id == actor.id,
                SupportBusinessAction.command_key == key,
            )
        )
        target = None
        project_scope_digest = existing.project_scope_digest if existing is not None else None
        if existing is None:
            if case.revision != payload.case_revision:
                raise _stale()
            target = await self._target(payload.user_id, payload.user_revision, payload.kind)
            if payload.kind == "request_summary":
                await read_linked_request_summary(
                    self.session, case.id, target.id, payload.source_event_id
                )
            if payload.kind in PROJECT_VIEW_KINDS:
                project_view = await masked_projects(
                    self.session, case.id, target.id, target.role, project_id=payload.project_id
                )
                if isinstance(project_view, MaskedProjects):
                    project_scope_digest = project_view.scope_digest
        recovery_binding = None
        if payload.kind == "recover":
            if target is not None:
                recovery_binding = _recovery_binding(target)
            elif existing is not None:
                recovery_binding = existing.recovery_destination_digest
        # The reason must be an operational description. Never retain common secret patterns.
        reason = redact_text(payload.reason)[:300]
        body = payload.model_dump(mode="json", exclude={"reason"})
        if payload.source_event_id is None:
            body.pop("source_event_id")
        if payload.project_id is None:
            body.pop("project_id")
        if project_scope_digest is not None:
            body["project_scope_digest"] = project_scope_digest
        if recovery_binding is not None:
            body["recovery_destination_digest"] = recovery_binding
        digest = _digest(
            json.dumps(
                {
                    **body,
                    "reason_digest": _digest(payload.reason),
                    "case_id": str(case.id),
                    "requester_id": str(actor.id),
                    "command_key": str(key),
                    "view_session": str(active.id) if payload.kind in _VIEW_KINDS else None,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        if existing is not None:
            if not compare_digest(existing.digest, digest):
                raise _stale()
            return BusinessActionRead.model_validate(existing)
        assert target is not None
        now = utc_now()
        action = SupportBusinessAction(
            id=uuid4(),
            case_id=case.id,
            requester_id=actor.id,
            requester_epoch=actor.grant_epoch,
            user_id=target.id,
            user_revision=target.access_revision,
            case_revision=case.revision,
            command_key=key,
            kind=payload.kind,
            reason_code=payload.reason_code,
            reason=reason,
            permission_key=payload.permission_key,
            permission_session_id=active.id if payload.kind in _VIEW_KINDS else None,
            source_event_id=payload.source_event_id,
            project_id=payload.project_id,
            project_scope_digest=project_scope_digest,
            recovery_destination_digest=recovery_binding,
            digest=digest,
            expires_at=now + timedelta(minutes=15),
        )
        self.session.add(action)
        await self.session.flush()
        self._audit(action, actor, "proposed", request_id)
        if support_session_deadline(active) <= utc_now():
            raise _denied()
        result = BusinessActionRead.model_validate(action)
        await self.session.commit()
        return result

    async def _protected_contact(self, action: SupportBusinessAction) -> bool:
        contact = await self.session.get(SupportBusinessContact, action.id)
        now = utc_now()
        return bool(
            contact is not None
            and contact.verifier_id != action.requester_id
            and compare_digest(contact.action_digest, action.digest)
            and action.expires_at - timedelta(minutes=15) <= contact.verified_at <= now
            and now < contact.expires_at <= action.expires_at
            and await self._assigned(action.case_id, contact.verifier_id, contact.verifier_epoch)
            and await self.session.scalar(
                SupportCustody.usable_custodians().where(
                    SupportOperator.id == contact.verifier_id,
                    SupportOperator.grant_epoch == contact.verifier_epoch,
                )
            )
            is not None
        )

    async def _check_contact_attestation(
        self,
        action: SupportBusinessAction,
        actor: SupportOperator,
        stage: BusinessActionStage,
        required_reviews: int,
        contact_ref: UUID,
    ) -> None:
        if (
            stage != "review"
            or required_reviews != 2
            or contact_ref.int == 0
            or await self.session.scalar(
                SupportCustody.usable_custodians().where(
                    SupportOperator.id == actor.id,
                    SupportOperator.grant_epoch == actor.grant_epoch,
                )
            )
            is None
        ):
            raise _denied()
        if await self.session.scalar(
            select(SupportBusinessContact.action_id)
            .where(
                (SupportBusinessContact.action_id == action.id)
                | (SupportBusinessContact.contact_ref == contact_ref)
            )
            .limit(1)
        ) is not None:
            raise _stale()

    async def _intent(
        self,
        case_id: UUID,
        action_id: UUID,
        actor: SupportOperator,
        stage: BusinessActionStage,
    ) -> tuple[SupportBusinessAction, User, int]:
        case, subject = await self._case(case_id, actor)
        action = await self.session.get(SupportBusinessAction, action_id, with_for_update=True)
        if action is None or action.case_id != case.id or action.user_id != subject.user_id:
            raise NotFoundException("Support account action")
        capability = _required_capability(action.kind)
        if await self.session.get(SupportOperatorGrant, (actor.id, capability)) is None:
            raise NotFoundException("Support account action")
        if (
            case.revision != action.case_revision
            or action.expires_at <= utc_now()
            or action.applied_at is not None
            or not await self._assigned(
                case.id, action.requester_id, action.requester_epoch, capability
            )
        ):
            raise _stale()
        if (stage == "review") == (actor.id == action.requester_id):
            raise _denied()
        target = await self._target(action.user_id, action.user_revision, action.kind)
        if action.kind == "request_summary":
            await read_linked_request_summary(
                self.session, case.id, target.id, action.source_event_id
            )
        if action.kind in PROJECT_VIEW_KINDS:
            project_view = await masked_projects(
                self.session, case.id, target.id, target.role, project_id=action.project_id
            )
            if isinstance(project_view, MaskedProjects) and (
                project_view.scope_digest != action.project_scope_digest
            ):
                raise _stale()
        if action.kind == "recover" and (
            action.recovery_destination_digest is None
            or not compare_digest(_recovery_binding(target), action.recovery_destination_digest)
        ):
            raise _stale()
        protected = action.kind not in _VIEW_KINDS and target.role in PROTECTED_USER_ROLES
        if stage == "review":
            if await self.session.get(SupportBusinessApproval, (action.id, actor.id)) is not None:
                raise _stale()
        elif not await self._has_live_approvals(action, capability, protected):
            raise _stale()
        return action, target, 2 if protected else 1

    async def _has_live_approvals(
        self, action: SupportBusinessAction, capability: str, protected: bool
    ) -> bool:
        approvals = await self.session.scalars(
            select(SupportBusinessApproval)
            .where(SupportBusinessApproval.action_id == action.id)
        )
        valid = [
            approval.reviewer_id
            for approval in approvals
            if approval.reviewer_id != action.requester_id
            and await self._assigned(
                action.case_id, approval.reviewer_id, approval.reviewer_epoch, capability
            )
        ]
        return len(valid) >= (2 if protected else 1) and (
            not protected or await self._protected_contact(action)
        )

    async def lock_recovery_delivery_target(self, action: SupportBusinessAction) -> User:
        await self.users.lock_access_management()
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))
        case = await self.session.get(SupportCase, action.case_id, with_for_update=True)
        subject = await self.session.get(SupportCaseSubject, action.case_id, with_for_update=True)
        if (
            action.kind != "recover"
            or action.applied_at is None
            or action.expires_at <= utc_now()
            or case is None or case.status not in {"open", "investigating"}
            or case.revision != action.case_revision
            or subject is None or subject.user_id != action.user_id
            or not await self._assigned(case.id, action.requester_id, action.requester_epoch)
        ):
            raise _stale()
        target = await self._target(action.user_id, action.user_revision + 1, action.kind)
        if (
            action.recovery_destination_digest is None
            or not compare_digest(_recovery_binding(target), action.recovery_destination_digest)
            or not await self._has_live_approvals(
                action, _CAPABILITY, target.role in PROTECTED_USER_ROLES
            )
        ):
            raise _stale()
        return target

    async def recovery_status(
        self, token: str | None, case_id: UUID, action_id: UUID, request_id: str
    ) -> SupportRecoveryStatus:
        actor, active = await self.identity.current(token)
        if await self.session.get(SupportOperatorGrant, (actor.id, _CAPABILITY)) is None:
            raise _denied()
        case, subject = await self._case(case_id, actor)
        action = await self.session.get(SupportBusinessAction, action_id)
        if (
            action is None or action.case_id != case.id or action.user_id != subject.user_id
            or action.kind != "recover"
        ):
            raise NotFoundException("Support recovery")
        snapshot = (
            await self.session.execute(
                select(SupportRecoveryDelivery, AuthOtpChallenge, User)
                .select_from(SupportRecoveryDelivery)
                .join(
                    AuthOtpChallenge,
                    AuthOtpChallenge.id == SupportRecoveryDelivery.challenge_id,
                )
                .outerjoin(User, User.id == action.user_id)
                .where(SupportRecoveryDelivery.action_id == action.id)
                .options(
                    load_only(
                        AuthOtpChallenge.expires_at, AuthOtpChallenge.consumed_at,
                        AuthOtpChallenge.deleted_at, AuthOtpChallenge.purpose,
                    ),
                    load_only(
                        User.id, User.email, User.is_active, User.deleted_at, User.role,
                        User.access_revision, User.recovery_email_verified_at,
                        User.recovery_email_digest,
                    ),
                )
            )
        ).one_or_none()
        delivery_state: RecoveryDeliveryState = "not_queued"
        reset_state: RecoveryResetState = "not_issued"
        delivery = None
        if snapshot is not None:
            delivery, challenge, user = snapshot
            match delivery.status:
                case "pending" | "dispatching" | "accepted" | "unknown" | "cancelled":
                    delivery_state = delivery.status
                case _:
                    raise _stale()
            reset_state = self._recovery_reset_state(action, delivery, challenge, user)
        now = utc_now()
        if support_session_deadline(active) <= now:
            raise AppException(
                "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
            )
        result = SupportRecoveryStatus(
            case_id=case.id,
            action_id=action.id,
            delivery_state=delivery_state,
            reset_state=reset_state,
            queued_at=delivery.created_at if delivery is not None else None,
            delivery_resolved_at=delivery.dispatch_finished_at if delivery is not None else None,
            completed_at=delivery.completed_at if delivery is not None else None,
        )
        self._audit(action, actor, "status_read", request_id)
        active.last_seen_at = now
        await self.session.commit()
        return result

    @staticmethod
    def _recovery_reset_state(
        action: SupportBusinessAction,
        delivery: SupportRecoveryDelivery,
        challenge: AuthOtpChallenge,
        user: User | None,
    ) -> RecoveryResetState:
        if delivery.completed_at is not None:
            return "completed"
        if delivery.status in {"unknown", "cancelled"}:
            return "unavailable"
        if (
            challenge.purpose != "support_password_reset"
            or challenge.deleted_at is not None or challenge.consumed_at is not None
            or user is None or user.deleted_at is not None or not user.is_active
            or user.role not in BUSINESS_ROLES
            or user.access_revision != action.user_revision + 1
        ):
            return "revoked"
        if challenge.expires_at <= utc_now():
            return "expired"
        try:
            binding = _recovery_binding(user)
        except AppException:
            return "revoked"
        if action.recovery_destination_digest is None or not compare_digest(
            binding, action.recovery_destination_digest
        ):
            return "revoked"
        return "ready" if delivery.status == "accepted" else "waiting"

    async def options(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        action_id: UUID,
        stage: BusinessActionStage,
        contact_ref: UUID | None = None,
    ) -> tuple[UUID, str, BusinessActionRead, int]:
        actor, active = await self._actor(token, csrf)
        action, _, reviews = await self._intent(case_id, action_id, actor, stage)
        if contact_ref is not None:
            await self._check_contact_attestation(action, actor, stage, reviews, contact_ref)
        if (
            stage == "execute"
            and action.kind in _VIEW_KINDS
            and (action.permission_session_id != active.id)
        ):
            raise _denied()
        now = utc_now()
        proof = SupportBusinessProof(
            id=uuid4(),
            action_id=action.id,
            stage=stage,
            contact_ref=contact_ref,
            session_id=active.id,
            challenge=token_bytes(32),
            expires_at=min(
                now + timedelta(minutes=2), action.expires_at, support_session_deadline(active)
            ),
        )
        if proof.expires_at <= now:
            raise _denied()
        self.session.add(proof)
        options = generate_authentication_options(
            rp_id=SUPPORT_HOST,
            challenge=proof.challenge,
            timeout=120_000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        result = BusinessActionRead.model_validate(action)
        await self.session.commit()
        return proof.id, options_to_json(options), result, reviews

    async def decide(
        self,
        token: str | None,
        csrf: str | None,
        case_id: UUID,
        action_id: UUID,
        stage: BusinessActionStage,
        challenge_id: UUID,
        digest: str,
        credential: dict[str, object],
        request_id: str,
        contact_ref: UUID | None = None,
    ) -> BusinessActionRead:
        actor, active = await self._actor(token, csrf)
        action, target, reviews = await self._intent(case_id, action_id, actor, stage)
        if (
            stage == "execute"
            and action.kind in _VIEW_KINDS
            and (action.permission_session_id != active.id)
        ):
            raise _denied()
        proof = await self.session.get(SupportBusinessProof, challenge_id, with_for_update=True)
        now = utc_now()
        if (
            not compare_digest(action.digest, digest)
            or proof is None
            or proof.action_id != action.id
            or proof.session_id != active.id
            or proof.stage != stage
            or proof.contact_ref != contact_ref
            or proof.consumed_at is not None
            or proof.expires_at <= now
        ):
            raise _stale()
        if contact_ref is not None:
            await self._check_contact_attestation(action, actor, stage, reviews, contact_ref)
        proof.consumed_at = now
        try:
            await self.identity.verify_assertion(actor.id, proof.challenge, credential)
        except (WebAuthnException, ValueError, AppException) as exc:
            self._audit(action, actor, "proof_denied", request_id)
            await self.session.commit()
            raise _denied() from exc
        now = utc_now()
        if min(support_session_deadline(active), proof.expires_at, action.expires_at) <= now:
            raise _stale()
        if stage == "review":
            self.session.add(
                SupportBusinessApproval(
                    action_id=action.id,
                    reviewer_id=actor.id,
                    reviewer_epoch=actor.grant_epoch,
                    occurred_at=now,
                    request_id=request_id,
                )
            )
            if contact_ref is not None:
                self.session.add(
                    SupportBusinessContact(
                        action_id=action.id,
                        verifier_id=actor.id,
                        verifier_epoch=actor.grant_epoch,
                        contact_ref=contact_ref,
                        action_digest=action.digest,
                        verified_at=now,
                        expires_at=action.expires_at,
                    )
                )
        elif action.kind in _VIEW_KINDS:
            if not target.is_active:
                raise _stale()
            live = await self.session.scalar(
                select(SupportPermissionView.id)
                .where(
                    SupportPermissionView.session_id == active.id,
                    SupportPermissionView.ended_at.is_(None),
                    SupportPermissionView.expires_at > now,
                    SupportPermissionView.last_seen_at > now - timedelta(minutes=10),
                )
                .limit(1)
            )
            if live is not None:
                raise _stale()
            self.session.add(
                SupportPermissionView(
                    id=action.id,
                    session_id=active.id,
                    last_seen_at=now,
                    expires_at=min(now + timedelta(minutes=20), active.expires_at),
                )
            )
            await self.session.flush()
            self.session.add(
                SupportPermissionViewEvent(
                    id=uuid4(),
                    view_id=action.id,
                    event="opened",
                    actor_id=actor.id,
                    occurred_at=now,
                    request_id=request_id,
                )
            )
            action.applied_at = now
            self._audit(action, actor, "applied", request_id)
        else:
            if target.role in PROTECTED_USER_ROLES and not await self._protected_contact(action):
                raise _stale()
            if action.kind == "unlock":
                if target.failed_login_attempts == 0 and target.locked_until is None:
                    raise _stale()
                target.failed_login_attempts = 0
                target.locked_until = None
            else:
                if (
                    action.kind == "disable"
                    and target.role in COMPANY_RESOURCE_ROLES
                    and not await self.users.has_other_usable_director(target.id)
                ):
                    raise AppException(
                        "At least one other director account must be able to sign in.",
                        status_code=409,
                        error_code="LAST_ACCESS_MANAGER_REQUIRED",
                    )
                if action.kind in {"disable", "reactivate"}:
                    target.is_active = action.kind == "reactivate"
                target.access_revision += 1
                auth = AuthRepository(self.session)
                await auth.revoke_user_authentication(target.id)
                if action.kind == "recover":
                    challenge_id = uuid4()
                    settings = get_settings()
                    otp = support_recovery_otp(settings, challenge_id)
                    hashed = (
                        support_recovery_otp_digest(settings, challenge_id, otp) if otp else None
                    )
                    if hashed is None:
                        raise _stale()
                    await auth.add_otp_challenge(
                        AuthOtpChallenge(
                            id=challenge_id,
                            user_id=target.id,
                            purpose="support_password_reset",
                            otp_hash=hashed,
                            expires_at=now
                            + timedelta(minutes=min(10, settings.otp_expire_minutes)),
                        )
                    )
                    self.session.add(
                        SupportRecoveryDelivery(
                            action_id=action.id, challenge_id=challenge_id,
                            status="pending", created_at=now,
                        )
                    )
            target.updated_at = now
            action.applied_at = now
            self._audit(action, actor, "applied", request_id)
        result = BusinessActionRead.model_validate(action)
        await self.session.commit()
        return result
