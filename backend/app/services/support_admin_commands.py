"""Plan, passkey-proof, and execute orchestration for Company Control Centre commands."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from hmac import compare_digest
from secrets import token_bytes
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import generate_authentication_options, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import UserVerificationRequirement

from app.config import get_settings
from app.models.auth import AuthOtpChallenge, AuthRefreshToken, AuthSession
from app.models.business_log_stream import BusinessLogStream
from app.models.hr import HrEmployee
from app.models.import_batch import ImportBatch
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.support_admin_commands import (
    SupportAdminCommand,
    SupportAdminCommandEvent,
    SupportAdminCommandProof,
    SupportSafeSetting,
)
from app.models.support_business_actions import SupportRecoveryDelivery
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.repositories.auth_repository import AuthRepository
from app.repositories.user_repository import UserRepository
from app.schemas.support_company_admin import (
    BulkAccountLifecycleCommand,
    ChangeBusinessRoleCommand,
    ChangeProjectMembershipCommand,
    CreateBusinessAccountCommand,
    RequestAccountRecoveryCommand,
    RetrySafeJobCommand,
    RevokeBusinessSessionCommand,
    SetAccountStateCommand,
    SupportAdminCommandPlanRequest,
    SupportAdminCommandRead,
    UnlockAccountCommand,
    UpdateSafeSettingCommand,
)
from app.services.email_service import EmailDeliveryError, EmailService
from app.services.hr_project_assignment import ACTIVE_ASSIGNMENT_EMPLOYMENT
from app.services.project_service import READ_ONLY_STATUSES
from app.services.support_admin_policy import (
    POLICY_VERSION,
    SAFE_SETTINGS_REGISTRY,
    TECHNICAL_COMMAND_POLICY,
    SupportActorContext,
    resolve_support_actor_context,
    validate_safe_setting_value,
)
from app.services.support_custody import _CUSTODY_LOCK
from app.services.support_directory import _masked_email
from app.services.support_identity import (
    SUPPORT_HOST,
    SupportIdentity,
    _digest,
    support_session_deadline,
)
from app.tasks.outbox import MAX_OUTBOX_ATTEMPTS, _build_dispatch_spec
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    BUSINESS_ROLE_LABELS,
    BUSINESS_ROLES,
    COMPANY_RESOURCE_ROLES,
    PROTECTED_USER_ROLES,
    permissions_for_role,
    validate_role,
)
from app.utils.recovery_destination import (
    is_recovery_issuance_enabled,
    recovery_destination_digest,
    verified_recovery_destination,
)
from app.utils.redaction import redact_text
from app.utils.security import generate_otp, hash_secret, utc_now

_COMMAND_LIFETIME = timedelta(minutes=15)
_PROOF_LIFETIME = timedelta(minutes=2)


def _stale(
    message: str = "The administrative command is stale or no longer actionable.",
) -> AppException:
    return AppException(message, status_code=409, error_code="SUPPORT_COMMAND_STALE")


def _denied(
    message: str = "This operator cannot perform the requested administrative command.",
    error_code: str = "SUPPORT_COMMAND_DENIED",
) -> AppException:
    return AppException(message, status_code=403, error_code=error_code)


def _to_read(command: SupportAdminCommand) -> SupportAdminCommandRead:
    payload = command.payload_json or {}
    return SupportAdminCommandRead(
        command_id=command.id,
        command_kind=command.command_kind,
        company_context="garrisons_single_company",
        operator_id=command.operator_id,
        session_id=command.session_id,
        case_id=command.case_id,
        authorization_mode=command.authorization_mode,  # type: ignore[arg-type]
        target_id=command.target_user_id,
        target_revision=command.target_revision,
        project_id=command.project_id,
        project_revision=command.project_revision,
        before=payload.get("before", {}),
        after=payload.get("after", {}),
        effects=payload.get("effects", []),
        denied_conditions=payload.get("denied_conditions", []),
        requires_action_passkey=True,
        policy_version=command.policy_version,
        plan_sha256=command.plan_sha256,
        reason_code=command.reason_code,
        reason=command.reason,
        status=command.status,  # type: ignore[arg-type]
        result=command.result_json,
        created_at=command.created_at,
        expires_at=command.expires_at,
        completed_at=command.completed_at,
    )


class SupportAdminCommands:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.identity = SupportIdentity(session)
        self.users = UserRepository(session)
        self.auth = AuthRepository(session)

    def _audit(
        self, command_id: UUID, actor_id: UUID, event: str, request_id: str
    ) -> None:
        self.session.add(
            SupportAdminCommandEvent(
                id=uuid4(),
                command_id=command_id,
                actor_id=actor_id,
                event=event,
                request_id=request_id,
                occurred_at=utc_now(),
            )
        )

    async def _lock_hierarchy(self, *, touches_users: bool = True) -> None:
        if touches_users:
            await self.users.lock_access_management()
        await self.session.execute(select(func.pg_advisory_xact_lock(_CUSTODY_LOCK)))

    async def get_command(
        self, token: str | None, command_id: UUID, request_id: str
    ) -> SupportAdminCommandRead:
        ctx, _, active = await resolve_support_actor_context(
            self.session, token, request_id=request_id
        )
        command = await self.session.get(SupportAdminCommand, command_id)
        if command is None or command.operator_id != ctx.operator_id:
            raise NotFoundException("Administrative command")
        rule = TECHNICAL_COMMAND_POLICY.get(command.command_kind)
        if rule is None or rule.required_capability not in ctx.capabilities:
            raise NotFoundException("Administrative command")
        now = utc_now()
        if command.status == "planned" and command.expires_at <= now:
            command.status = "expired"
        if support_session_deadline(active) <= now:
            raise AppException(
                "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
            )
        active.last_seen_at = now
        await self.session.commit()
        return _to_read(command)

    async def plan(
        self,
        token: str | None,
        csrf: str | None,
        idempotency_key: str,
        payload: SupportAdminCommandPlanRequest,
        request_id: str,
    ) -> SupportAdminCommandRead:
        cleaned_key = idempotency_key.strip()
        if not 1 <= len(cleaned_key) <= 64:
            raise AppException(
                "Idempotency-Key must be between 1 and 64 characters.",
                status_code=422,
                error_code="INVALID_IDEMPOTENCY_KEY",
            )
        rule = TECHNICAL_COMMAND_POLICY.get(payload.command_kind)
        if rule is None:
            raise _denied()
        touches_users = payload.command_kind not in {"update_safe_setting", "retry_safe_job"}
        await self._lock_hierarchy(touches_users=touches_users)
        ctx, _, active = await resolve_support_actor_context(
            self.session,
            token,
            csrf,
            request_id=request_id,
            required_capability=rule.required_capability,
            require_csrf=True,
        )

        canonical_request = payload.model_dump(mode="json", exclude={"reason"})
        request_sha256 = _digest(
            json.dumps(
                {
                    **canonical_request,
                    "reason_digest": _digest(payload.reason),
                    "operator_id": str(ctx.operator_id),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

        existing = await self.session.scalar(
            select(SupportAdminCommand)
            .where(
                SupportAdminCommand.operator_id == ctx.operator_id,
                SupportAdminCommand.command_kind == payload.command_kind,
                SupportAdminCommand.idempotency_key == cleaned_key,
            )
            .with_for_update()
        )
        if existing is not None:
            stored_req_sha = (existing.payload_json or {}).get("request_sha256")
            if not isinstance(stored_req_sha, str) or not compare_digest(
                stored_req_sha, request_sha256
            ):
                raise AppException(
                    "This Idempotency-Key was already used with a different command payload.",
                    status_code=409,
                    error_code="SUPPORT_COMMAND_IDEMPOTENCY_CONFLICT",
                )
            self._audit(existing.id, ctx.operator_id, "replayed", request_id)
            active.last_seen_at = utc_now()
            await self.session.commit()
            return _to_read(existing)

        plan_details = await self._build_plan_details(ctx, payload)
        now = utc_now()
        reason = redact_text(payload.reason)[:300]
        plan_sha256 = _digest(
            json.dumps(
                {
                    "operator_id": str(ctx.operator_id),
                    "session_id": str(ctx.session_id),
                    "authorization_mode": ctx.authorization_mode,
                    "command_kind": payload.command_kind,
                    "idempotency_key": cleaned_key,
                    "policy_version": POLICY_VERSION,
                    "request_sha256": request_sha256,
                    "target_user_id": (
                        str(plan_details["target_user_id"])
                        if plan_details["target_user_id"]
                        else None
                    ),
                    "target_revision": plan_details["target_revision"],
                    "project_id": (
                        str(plan_details["project_id"])
                        if plan_details["project_id"]
                        else None
                    ),
                    "project_revision": plan_details["project_revision"],
                    "before": plan_details["before"],
                    "after": plan_details["after"],
                    "binding": plan_details.get("binding"),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

        command = SupportAdminCommand(
            id=uuid4(),
            operator_id=ctx.operator_id,
            operator_epoch=ctx.grant_epoch,
            session_id=ctx.session_id,
            case_id=None,
            authorization_mode=ctx.authorization_mode,
            command_kind=payload.command_kind,
            idempotency_key=cleaned_key,
            target_user_id=plan_details["target_user_id"],
            target_revision=plan_details["target_revision"],
            project_id=plan_details["project_id"],
            project_revision=plan_details["project_revision"],
            policy_version=POLICY_VERSION,
            reason_code=payload.reason_code,
            reason=reason,
            plan_sha256=plan_sha256,
            payload_json={
                "request": canonical_request,
                "request_sha256": request_sha256,
                "before": plan_details["before"],
                "after": plan_details["after"],
                "effects": plan_details["effects"],
                "denied_conditions": plan_details["denied_conditions"],
                "binding": plan_details.get("binding"),
            },
            result_json=None,
            status="planned",
            created_at=now,
            expires_at=now + _COMMAND_LIFETIME,
            completed_at=None,
        )
        self.session.add(command)
        await self.session.flush()
        self._audit(command.id, ctx.operator_id, "planned", request_id)
        if support_session_deadline(active) <= utc_now():
            raise AppException(
                "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
            )
        active.last_seen_at = utc_now()
        await self.session.commit()
        return _to_read(command)

    async def options(
        self,
        token: str | None,
        csrf: str | None,
        command_id: UUID,
        request_id: str,
    ) -> tuple[UUID, str, SupportAdminCommandRead]:
        await self._lock_hierarchy(touches_users=True)
        ctx, _, active = await resolve_support_actor_context(
            self.session,
            token,
            csrf,
            request_id=request_id,
            require_csrf=True,
        )
        command = await self._load_actionable_command(ctx, command_id)
        await self._verify_live_preconditions(ctx, command)
        now = utc_now()
        proof = SupportAdminCommandProof(
            id=uuid4(),
            command_id=command.id,
            session_id=active.id,
            challenge=token_bytes(32),
            expires_at=min(
                now + _PROOF_LIFETIME,
                command.expires_at,
                support_session_deadline(active),
            ),
        )
        if proof.expires_at <= now:
            raise _stale("The command or support session expired before a proof could be issued.")
        self.session.add(proof)
        self._audit(command.id, ctx.operator_id, "proof_issued", request_id)
        webauthn_options = generate_authentication_options(
            rp_id=SUPPORT_HOST,
            challenge=proof.challenge,
            timeout=120_000,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        read_model = _to_read(command)
        active.last_seen_at = now
        await self.session.commit()
        return proof.id, options_to_json(webauthn_options), read_model

    async def execute(
        self,
        token: str | None,
        csrf: str | None,
        command_id: UUID,
        challenge_id: UUID,
        expected_plan_sha256: str,
        credential: dict[str, object],
        request_id: str,
    ) -> SupportAdminCommandRead:
        await self._lock_hierarchy(touches_users=True)
        ctx, _, active = await resolve_support_actor_context(
            self.session,
            token,
            csrf,
            request_id=request_id,
            require_csrf=True,
        )
        command = await self._load_actionable_command(ctx, command_id)
        proof = await self.session.get(
            SupportAdminCommandProof, challenge_id, with_for_update=True
        )
        now = utc_now()
        if (
            not compare_digest(command.plan_sha256, expected_plan_sha256)
            or proof is None
            or proof.command_id != command.id
            or proof.session_id != active.id
            or proof.consumed_at is not None
            or proof.expires_at <= now
        ):
            raise _stale(
                "A fresh action-bound passkey proof matching the current plan is required."
            )
        proof.consumed_at = now
        try:
            await self.identity.verify_assertion(ctx.operator_id, proof.challenge, credential)
        except (WebAuthnException, ValueError, AppException) as exc:
            self._audit(command.id, ctx.operator_id, "proof_denied", request_id)
            await self.session.commit()
            raise _denied("Passkey assertion could not be verified for this command.") from exc

        now = utc_now()
        if min(support_session_deadline(active), proof.expires_at, command.expires_at) <= now:
            raise _stale("The command proof expired before execution completed.")

        post_commit_mail: dict[str, Any] | None = await self._apply_command(ctx, command, now)
        self._audit(command.id, ctx.operator_id, "executed", request_id)
        active.last_seen_at = now
        await self.session.commit()

        if post_commit_mail is not None:
            await self._deliver_post_commit_mail(
                command.id, ctx.operator_id, request_id, post_commit_mail
            )
            refreshed = await self.session.get(SupportAdminCommand, command.id)
            assert refreshed is not None
            return _to_read(refreshed)

        return _to_read(command)

    async def _load_actionable_command(
        self, ctx: SupportActorContext, command_id: UUID
    ) -> SupportAdminCommand:
        command = await self.session.get(SupportAdminCommand, command_id, with_for_update=True)
        if command is None:
            raise NotFoundException("Administrative command")
        if (
            command.operator_id != ctx.operator_id
            or command.session_id != ctx.session_id
            or command.operator_epoch != ctx.grant_epoch
            or command.authorization_mode != ctx.authorization_mode
        ):
            raise _denied(
                "Commands must be confirmed by the same operator and session that planned them."
            )
        rule = TECHNICAL_COMMAND_POLICY.get(command.command_kind)
        if rule is None or rule.required_capability not in ctx.capabilities:
            raise _denied()
        if command.status != "planned" or command.expires_at <= utc_now():
            raise _stale()
        return command

    async def _require_target_user(
        self, user_id: UUID, expected_revision: int, *, include_active_directors: bool = False
    ) -> User:
        locked = await self.users.lock_users(
            user_id, include_active_directors=include_active_directors
        )
        user = locked.get(user_id)
        if user is None or user.deleted_at is not None or user.role not in BUSINESS_ROLES:
            raise NotFoundException("Business account")
        if user.access_revision != expected_revision:
            raise _stale("The target account changed since preview. Reload and plan again.")
        return user

    async def _build_plan_details(
        self, ctx: SupportActorContext, payload: SupportAdminCommandPlanRequest
    ) -> dict[str, Any]:
        if isinstance(payload, CreateBusinessAccountCommand):
            role = validate_role(payload.role)
            if role not in BUSINESS_ROLES:
                raise _denied("Technical roles cannot be assigned to business accounts.")
            email_lower = payload.email.lower().strip()
            code_clean = payload.employee_code.strip()
            existing_user = await self.session.scalar(
                select(User.id).where(
                    User.deleted_at.is_(None),
                    (func.lower(User.email) == email_lower)
                    | (func.lower(User.employee_code) == code_clean.casefold()),
                )
            )
            if existing_user is not None:
                raise AppException(
                    "A user with this email or employee code already exists.",
                    status_code=409,
                    error_code="USER_ALREADY_EXISTS",
                )
            project_summaries: list[dict[str, Any]] = []
            for spec in payload.project_assignments:
                proj = await self.session.get(Project, spec.project_id, with_for_update=True)
                if proj is None or proj.deleted_at is not None:
                    raise NotFoundException("Project")
                if proj.status in READ_ONLY_STATUSES:
                    raise AppException(
                        f"Project {proj.code} is read-only.",
                        status_code=409,
                        error_code="PROJECT_READ_ONLY",
                    )
                if proj.revision != spec.expected_project_revision:
                    raise _stale(f"Project {proj.code} revision changed.")
                project_summaries.append(
                    {
                        "project_id": str(proj.id),
                        "project_code": proj.code,
                        "expected_project_revision": proj.revision,
                        "role_in_project": spec.role_in_project,
                    }
                )
            return {
                "target_user_id": None,
                "target_revision": None,
                "project_id": (
                    payload.project_assignments[0].project_id
                    if len(payload.project_assignments) == 1
                    else None
                ),
                "project_revision": (
                    payload.project_assignments[0].expected_project_revision
                    if len(payload.project_assignments) == 1
                    else None
                ),
                "before": {"account_exists": False},
                "after": {
                    "full_name": payload.full_name.strip(),
                    "email_masked": _masked_email(email_lower),
                    "employee_code": code_clean,
                    "role": role,
                    "role_label": BUSINESS_ROLE_LABELS.get(role, role),
                    "is_active": True,
                    "project_assignments": project_summaries,
                },
                "effects": [
                    "invitation_pending",
                    "recipient_mediated_credentials_only",
                    "business_approvals_unchanged",
                    "hr_employee_record_not_implicitly_created",
                ],
                "denied_conditions": [
                    "Owner never receives or views the recipient's password or one-time code."
                ],
                "binding": {
                    "email_digest": _digest(email_lower),
                    "employee_code_digest": _digest(code_clean.casefold()),
                },
            }

        if isinstance(payload, SetAccountStateCommand):
            target = await self._require_target_user(
                payload.target_user_id,
                payload.expected_user_revision,
                include_active_directors=not payload.active,
            )
            if target.is_active == payload.active:
                raise _stale("The target account already has the requested active state.")
            if (
                not payload.active
                and target.role in COMPANY_RESOURCE_ROLES
                and not await self.users.has_other_usable_director(target.id)
            ):
                raise AppException(
                    "At least one other director account must be able to sign in.",
                    status_code=409,
                    error_code="LAST_ACCESS_MANAGER_REQUIRED",
                )
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "is_active": target.is_active,
                    "access_revision": target.access_revision,
                },
                "after": {
                    "is_active": payload.active,
                    "access_revision": target.access_revision + 1,
                },
                "effects": [
                    "sessions_will_be_revoked",
                    "access_revision_incremented",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [],
            }

        if isinstance(payload, UnlockAccountCommand):
            target = await self._require_target_user(
                payload.target_user_id, payload.expected_user_revision
            )
            now = utc_now()
            is_locked = bool(target.locked_until is not None and target.locked_until > now)
            if target.failed_login_attempts == 0 and not is_locked:
                raise _stale("The target account does not have an active sign-in lock.")
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "locked": is_locked,
                    "failed_login_attempts": target.failed_login_attempts,
                },
                "after": {"locked": False, "failed_login_attempts": 0},
                "effects": ["failed_login_lock_cleared", "business_approvals_unchanged"],
                "denied_conditions": [],
            }

        if isinstance(payload, ChangeBusinessRoleCommand):
            new_role = validate_role(payload.new_role)
            if new_role not in BUSINESS_ROLES:
                raise _denied("Technical roles cannot be assigned through business role commands.")
            target = await self._require_target_user(
                payload.target_user_id,
                payload.expected_user_revision,
                include_active_directors=True,
            )
            if target.role == new_role:
                raise _stale("The target account already holds that business role.")
            if (
                target.is_active
                and target.role in COMPANY_RESOURCE_ROLES
                and new_role not in COMPANY_RESOURCE_ROLES
                and not await self.users.has_other_usable_director(target.id)
            ):
                raise AppException(
                    "At least one other director account must be able to sign in.",
                    status_code=409,
                    error_code="LAST_ACCESS_MANAGER_REQUIRED",
                )
            old_perms = set(permissions_for_role(target.role))
            new_perms = set(permissions_for_role(new_role))
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "role": target.role,
                    "role_label": BUSINESS_ROLE_LABELS.get(target.role, target.role),
                    "access_revision": target.access_revision,
                },
                "after": {
                    "role": new_role,
                    "role_label": BUSINESS_ROLE_LABELS.get(new_role, new_role),
                    "access_revision": target.access_revision + 1,
                    "gained_permissions": sorted(new_perms - old_perms),
                    "lost_permissions": sorted(old_perms - new_perms),
                },
                "effects": [
                    "sessions_will_be_revoked",
                    "access_revision_incremented",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [
                    (
                        "Role change does not grant self-approval or enable "
                        "policy-disabled finance/payroll writes."
                    )
                ],
            }

        if isinstance(payload, ChangeProjectMembershipCommand):
            target = await self._require_target_user(
                payload.target_user_id, payload.expected_user_revision
            )
            project = await self.session.get(Project, payload.project_id, with_for_update=True)
            if project is None or project.deleted_at is not None:
                raise NotFoundException("Project")
            if project.status in READ_ONLY_STATUSES:
                raise AppException(
                    "Completed or cancelled projects are read-only.",
                    status_code=409,
                    error_code="PROJECT_READ_ONLY",
                )
            if project.revision != payload.expected_project_revision:
                raise AppException(
                    (
                        "Project revision changed. Reload the project before "
                        "planning membership changes."
                    ),
                    status_code=409,
                    error_code="PROJECT_REVISION_CONFLICT",
                )
            existing_member = await self.session.scalar(
                select(ProjectMember)
                .where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == target.id,
                    ProjectMember.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if payload.action == "assign":
                if not target.is_active:
                    raise AppException(
                        "Inactive accounts cannot be assigned to projects.",
                        status_code=409,
                        error_code="USER_INACTIVE",
                    )
                if existing_member is not None:
                    raise AppException(
                        "User is already assigned to this project.",
                        status_code=409,
                        error_code="PROJECT_MEMBER_EXISTS",
                    )
                linked_emp = await self.session.scalar(
                    select(HrEmployee).where(HrEmployee.user_id == target.id)
                )
                if linked_emp is not None and (
                    linked_emp.deleted_at is not None
                    or linked_emp.employment_status not in ACTIVE_ASSIGNMENT_EMPLOYMENT
                ):
                    raise AppException(
                        (
                            "Linked employee record is not in an active employment "
                            "status for project assignment."
                        ),
                        status_code=409,
                        error_code="EMPLOYEE_NOT_ELIGIBLE_FOR_PROJECT",
                    )
            else:
                if existing_member is None:
                    raise AppException(
                        "Project membership not found.",
                        status_code=404,
                        error_code="PROJECT_MEMBER_NOT_FOUND",
                    )
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": project.id,
                "project_revision": project.revision,
                "before": {
                    "project_code": project.code,
                    "is_member": existing_member is not None,
                    "role_in_project": (
                        existing_member.role_in_project if existing_member else None
                    ),
                    "project_revision": project.revision,
                    "access_revision": target.access_revision,
                },
                "after": {
                    "project_code": project.code,
                    "is_member": payload.action == "assign",
                    "role_in_project": (
                        payload.role_in_project if payload.action == "assign" else None
                    ),
                    "project_revision": project.revision + 1,
                    "access_revision": target.access_revision + 1,
                },
                "effects": [
                    "project_revision_incremented",
                    "access_revision_incremented",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [],
            }

        if isinstance(payload, RequestAccountRecoveryCommand):
            target = await self._require_target_user(
                payload.target_user_id, payload.expected_user_revision
            )
            if not target.is_active:
                raise AppException(
                    "Inactive accounts cannot receive recovery codes.",
                    status_code=409,
                    error_code="USER_INACTIVE",
                )
            if target.role in PROTECTED_USER_ROLES and ctx.authorization_mode == "single_owner":
                raise _denied(
                    TECHNICAL_COMMAND_POLICY["request_account_recovery"].protected_target_note,
                    error_code="PROTECTED_TARGET_SOLO_RECOVERY_DENIED",
                )
            settings = get_settings()
            if not is_recovery_issuance_enabled(settings, support_host=SUPPORT_HOST):
                raise _denied("Support recovery issuance is not enabled.")
            binding = verified_recovery_destination(
                settings,
                target.id,
                target.email,
                target.recovery_email_digest,
                target.recovery_email_verified_at,
            )
            if binding is None:
                raise AppException(
                    "The current recovery destination has not been verified.",
                    status_code=409,
                    error_code="SUPPORT_RECOVERY_DESTINATION_UNVERIFIED",
                )
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "access_revision": target.access_revision,
                    "destination_masked": _masked_email(target.email),
                },
                "after": {
                    "access_revision": target.access_revision + 1,
                    "destination_masked": _masked_email(target.email),
                    "recovery_delivery": "recipient_only",
                },
                "effects": [
                    "sessions_will_be_revoked",
                    "invitation_pending",
                    "recipient_mediated_credentials_only",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [
                    (
                        "Recovery code and reset token are never displayed or "
                        "returned to the technical operator."
                    )
                ],
                "binding": {"recovery_destination_digest": binding},
            }

        if isinstance(payload, RevokeBusinessSessionCommand):
            target = await self._require_target_user(
                payload.target_user_id, payload.expected_user_revision
            )
            now = utc_now()
            legacy_unindexed = int(
                await self.session.scalar(
                    select(func.count(AuthRefreshToken.id)).where(
                        AuthRefreshToken.user_id == target.id,
                        AuthRefreshToken.session_id.is_(None),
                        AuthRefreshToken.revoked_at.is_(None),
                        AuthRefreshToken.deleted_at.is_(None),
                        AuthRefreshToken.expires_at > now,
                    )
                )
                or 0
            )
            if payload.scope == "selected":
                assert payload.session_id is not None
                auth_session = await self.session.get(
                    AuthSession, payload.session_id, with_for_update=True
                )
                if auth_session is None or auth_session.user_id != target.id:
                    raise NotFoundException("Business session")
                if auth_session.revoked_at is not None:
                    raise _stale("The selected business session is already revoked.")
                effects = ["selected_session_will_be_revoked", "business_approvals_unchanged"]
                if legacy_unindexed > 0:
                    effects.append("legacy_unindexed_tokens_present_require_all_session_revocation")
                return {
                    "target_user_id": target.id,
                    "target_revision": target.access_revision,
                    "project_id": None,
                    "project_revision": None,
                    "before": {
                        "scope": "selected",
                        "session_id": str(auth_session.id),
                        "session_state": "active",
                    },
                    "after": {
                        "scope": "selected",
                        "session_id": str(auth_session.id),
                        "session_state": "revoked",
                    },
                    "effects": effects,
                    "denied_conditions": [],
                    "binding": {"target_session_id": str(auth_session.id)},
                }
            active_sessions = int(
                await self.session.scalar(
                    select(func.count(AuthSession.id)).where(
                        AuthSession.user_id == target.id,
                        AuthSession.revoked_at.is_(None),
                        AuthSession.expires_at > now,
                    )
                )
                or 0
            )
            return {
                "target_user_id": target.id,
                "target_revision": target.access_revision,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "scope": "all",
                    "active_sessions": active_sessions,
                    "access_revision": target.access_revision,
                },
                "after": {
                    "scope": "all",
                    "active_sessions": 0,
                    "access_revision": target.access_revision + 1,
                },
                "effects": [
                    "sessions_will_be_revoked",
                    "access_revision_incremented",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [],
            }

        if isinstance(payload, UpdateSafeSettingCommand):
            cleaned_val = validate_safe_setting_value(payload.setting_key, payload.value)
            setting_spec = SAFE_SETTINGS_REGISTRY[payload.setting_key]
            stored = await self.session.get(
                SupportSafeSetting, payload.setting_key, with_for_update=True
            )
            current_rev = stored.revision if stored is not None else 0
            current_val = (
                stored.value_json.get("value", setting_spec.default_value)
                if stored is not None and isinstance(stored.value_json, dict)
                else setting_spec.default_value
            )
            if current_rev != payload.expected_revision:
                raise _stale("The setting revision changed since preview.")
            return {
                "target_user_id": None,
                "target_revision": current_rev,
                "project_id": None,
                "project_revision": None,
                "before": {
                    "setting_key": payload.setting_key,
                    "value": current_val,
                    "revision": current_rev,
                },
                "after": {
                    "setting_key": payload.setting_key,
                    "value": cleaned_val,
                    "revision": current_rev + 1,
                    "effect": setting_spec.effect,
                },
                "effects": [
                    f"setting_effect_{setting_spec.effect}",
                    "business_approvals_unchanged",
                ],
                "denied_conditions": [],
                "binding": {"setting_key": payload.setting_key, "expected_revision": current_rev},
            }

        if isinstance(payload, RetrySafeJobCommand):
            job_info = await self._validate_retryable_job(
                payload.job_source, payload.job_id
            )
            return {
                "target_user_id": None,
                "target_revision": None,
                "project_id": None,
                "project_revision": None,
                "before": job_info["before"],
                "after": job_info["after"],
                "effects": ["original_payload_preserved", "business_approvals_unchanged"],
                "denied_conditions": [],
                "binding": job_info["binding"],
            }

        if isinstance(payload, BulkAccountLifecycleCommand):
            return await self._plan_bulk_lifecycle(payload)

        raise _denied()

    async def _validate_retryable_job(
        self, job_source: str, job_id: UUID
    ) -> dict[str, Any]:
        if job_source == "task_outbox":
            entry = await self.session.get(TaskOutbox, job_id, with_for_update=True)
            if entry is None:
                raise NotFoundException("Outbox job")
            if entry.task_name not in {"generate_report_pdf", "run_import_async"}:
                raise _denied("This task type is not eligible for technical retry.")
            if entry.status != "failed":
                raise _stale("Only terminal failed outbox jobs can be retried.")
            if _build_dispatch_spec(entry) is None:
                raise AppException(
                    "The outbox job payload is invalid or its encryption key is unavailable.",
                    status_code=409,
                    error_code="SUPPORT_JOB_PAYLOAD_UNAVAILABLE",
                )
            if entry.task_name == "run_import_async" and entry.args_json:
                batch_id = UUID(str(entry.args_json[0]))
                actor_id = UUID(str(entry.args_json[1]))
                actor = await self.session.get(User, actor_id)
                if actor is None or not actor.is_active or actor.deleted_at is not None:
                    raise AppException(
                        "The original import actor is no longer active.",
                        status_code=409,
                        error_code="SUPPORT_JOB_ACTOR_INACTIVE",
                    )
                batch = await self.session.get(ImportBatch, batch_id)
                if batch is not None and batch.status == "completed":
                    raise _stale("The import batch has already completed.")
            return {
                "before": {
                    "job_source": "task_outbox",
                    "job_id": str(entry.id),
                    "task_name": entry.task_name,
                    "status": entry.status,
                    "attempts": entry.attempts,
                },
                "after": {
                    "job_source": "task_outbox",
                    "job_id": str(entry.id),
                    "task_name": entry.task_name,
                    "status": "pending",
                },
                "binding": {
                    "job_source": "task_outbox",
                    "job_id": str(entry.id),
                    "dedupe_key": entry.dedupe_key,
                },
            }
        delivery = await self.session.get(
            SupportRecoveryDelivery, job_id, with_for_update=True
        )
        if delivery is None:
            raise NotFoundException("Recovery delivery job")
        if delivery.status != "unknown" or delivery.completed_at is not None:
            raise _stale("Only recovery deliveries in 'unknown' transport state can be retried.")
        return {
            "before": {
                "job_source": "support_recovery_delivery",
                "job_id": str(delivery.action_id),
                "status": delivery.status,
            },
            "after": {
                "job_source": "support_recovery_delivery",
                "job_id": str(delivery.action_id),
                "status": "pending",
            },
            "binding": {
                "job_source": "support_recovery_delivery",
                "job_id": str(delivery.action_id),
                "challenge_id": str(delivery.challenge_id),
            },
        }

    async def _plan_bulk_lifecycle(
        self, payload: BulkAccountLifecycleCommand
    ) -> dict[str, Any]:
        target_ids = [item.user_id for item in payload.targets]
        expected_map = {item.user_id: item.expected_user_revision for item in payload.targets}
        locked = await self.users.lock_users(
            *target_ids, include_active_directors=(payload.operation == "disable")
        )
        now = utc_now()
        preview_items: list[dict[str, Any]] = []
        disabling_director_ids: set[UUID] = set()
        for uid in target_ids:
            user = locked.get(uid)
            if user is None or user.deleted_at is not None or user.role not in BUSINESS_ROLES:
                raise NotFoundException("Business account")
            if user.access_revision != expected_map[uid]:
                raise _stale(f"Account {user.full_name} revision changed since selection.")
            if payload.operation == "disable":
                if not user.is_active:
                    raise _stale(f"Account {user.full_name} is already inactive.")
                if user.role in COMPANY_RESOURCE_ROLES:
                    disabling_director_ids.add(user.id)
            elif payload.operation == "reactivate":
                if user.is_active:
                    raise _stale(f"Account {user.full_name} is already active.")
            elif payload.operation == "unlock":
                is_locked = bool(user.locked_until is not None and user.locked_until > now)
                if user.failed_login_attempts == 0 and not is_locked:
                    raise _stale(f"Account {user.full_name} is not locked.")
            preview_items.append(
                {
                    "user_id": str(user.id),
                    "full_name": user.full_name,
                    "role": user.role,
                    "expected_revision": user.access_revision,
                }
            )
        if disabling_director_ids:
            remaining_director = await self.session.scalar(
                select(User.id)
                .where(
                    User.id.not_in(disabling_director_ids),
                    User.role.in_(COMPANY_RESOURCE_ROLES),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.password_hash.is_not(None),
                    User.password_hash != "",
                    (User.locked_until.is_(None) | (User.locked_until <= now)),
                )
                .limit(1)
            )
            if remaining_director is None:
                raise AppException(
                    "Bulk disable would leave no active, unlocked director account.",
                    status_code=409,
                    error_code="LAST_ACCESS_MANAGER_REQUIRED",
                )
        return {
            "target_user_id": None,
            "target_revision": None,
            "project_id": None,
            "project_revision": None,
            "before": {"operation": payload.operation, "target_count": len(preview_items)},
            "after": {"operation": payload.operation, "targets": preview_items},
            "effects": [
                f"bulk_{payload.operation}_up_to_{len(preview_items)}_accounts",
                "business_approvals_unchanged",
            ],
            "denied_conditions": [],
            "binding": {"targets": preview_items},
        }

    async def _verify_live_preconditions(
        self, ctx: SupportActorContext, command: SupportAdminCommand
    ) -> None:
        raw_req = (command.payload_json or {}).get("request", {})
        kind = command.command_kind
        if kind == "create_business_account":
            email_lower = str(raw_req.get("email", "")).lower().strip()
            code_clean = str(raw_req.get("employee_code", "")).strip()
            existing = await self.session.scalar(
                select(User.id).where(
                    User.deleted_at.is_(None),
                    (func.lower(User.email) == email_lower)
                    | (func.lower(User.employee_code) == code_clean.casefold()),
                )
            )
            if existing is not None:
                raise AppException(
                    "A user with this email or employee code already exists.",
                    status_code=409,
                    error_code="USER_ALREADY_EXISTS",
                )
            return
        if kind in {
            "set_account_state",
            "unlock_account",
            "change_business_role",
            "change_project_membership",
            "request_account_recovery",
            "revoke_business_session",
        }:
            assert command.target_user_id is not None and command.target_revision is not None
            target = await self._require_target_user(
                command.target_user_id, command.target_revision
            )
            if kind == "request_account_recovery":
                if target.role in PROTECTED_USER_ROLES and ctx.authorization_mode == "single_owner":
                    raise _denied(
                        TECHNICAL_COMMAND_POLICY["request_account_recovery"].protected_target_note,
                        error_code="PROTECTED_TARGET_SOLO_RECOVERY_DENIED",
                    )
                binding = (command.payload_json or {}).get("binding", {}).get(
                    "recovery_destination_digest"
                )
                current_binding = verified_recovery_destination(
                    get_settings(),
                    target.id,
                    target.email,
                    target.recovery_email_digest,
                    target.recovery_email_verified_at,
                )
                if not binding or not current_binding or not compare_digest(
                    binding, current_binding
                ):
                    raise _stale("The target account's verified recovery destination changed.")
            if kind == "change_project_membership":
                assert command.project_id is not None and command.project_revision is not None
                project = await self.session.get(
                    Project, command.project_id, with_for_update=True
                )
                if (
                    project is None
                    or project.deleted_at is not None
                    or project.revision != command.project_revision
                    or project.status in READ_ONLY_STATUSES
                ):
                    raise _stale("The target project changed or became read-only.")
            return
        if kind == "update_safe_setting":
            setting_key = str(raw_req.get("setting_key", ""))
            stored = await self.session.get(
                SupportSafeSetting, setting_key, with_for_update=True
            )
            current_rev = stored.revision if stored is not None else 0
            if current_rev != command.target_revision:
                raise _stale("The setting revision changed since preview.")
            return
        if kind == "retry_safe_job":
            await self._validate_retryable_job(
                str(raw_req.get("job_source", "")),
                UUID(str(raw_req.get("job_id"))),
            )
            return

    async def _apply_command(
        self,
        ctx: SupportActorContext,
        command: SupportAdminCommand,
        now: datetime,
    ) -> dict[str, Any] | None:
        raw_req = (command.payload_json or {}).get("request", {})
        raw_with_reason = {**raw_req, "reason": command.reason}
        kind = command.command_kind

        if kind == "create_business_account":
            parsed = CreateBusinessAccountCommand.model_validate(raw_with_reason)
            await self._verify_live_preconditions(ctx, command)
            role = validate_role(parsed.role)
            email_lower = parsed.email.lower().strip()
            code_clean = parsed.employee_code.strip()
            user_id = uuid4()
            settings = get_settings()
            rec_digest = recovery_destination_digest(settings, user_id, email_lower)
            user = User(
                id=user_id,
                email=email_lower,
                full_name=parsed.full_name.strip(),
                role=role,
                employee_code=code_clean,
                phone=parsed.phone.strip(),
                designation=parsed.designation.strip() if parsed.designation else None,
                password_hash=None,
                is_active=True,
                access_revision=0,
                must_change_password=True,
                recovery_email_digest=rec_digest,
                recovery_email_verified_at=now if rec_digest else None,
            )
            try:
                await self.users.add(user)
                assigned_codes: list[str] = []
                for spec in parsed.project_assignments:
                    proj = await self.session.get(
                        Project, spec.project_id, with_for_update=True
                    )
                    if (
                        proj is None
                        or proj.deleted_at is not None
                        or proj.status in READ_ONLY_STATUSES
                        or proj.revision != spec.expected_project_revision
                    ):
                        raise _stale("A selected project changed before execution.")
                    self.session.add(
                        ProjectMember(
                            project_id=proj.id,
                            user_id=user.id,
                            role_in_project=spec.role_in_project or None,
                        )
                    )
                    proj.revision += 1
                    assigned_codes.append(proj.code)
                otp = generate_otp()
                challenge = await self.auth.add_otp_challenge(
                    AuthOtpChallenge(
                        id=uuid4(),
                        user_id=user.id,
                        purpose="password_reset",
                        otp_hash=hash_secret(otp),
                        expires_at=now + timedelta(minutes=settings.otp_expire_minutes),
                    )
                )
            except IntegrityError as exc:
                raise AppException(
                    "A user with this email or employee code already exists.",
                    status_code=409,
                    error_code="USER_ALREADY_EXISTS",
                ) from exc
            command.target_user_id = user.id
            command.status = "delivery_pending"
            command.completed_at = now
            command.result_json = {
                "user_id": str(user.id),
                "account_state": "created",
                "invitation_state": "pending",
                "assigned_projects": assigned_codes,
                "access_revision": user.access_revision,
            }
            return {
                "kind": "invitation",
                "recipient": user.email,
                "full_name": user.full_name,
                "otp": otp,
                "challenge_id": challenge.id,
            }

        if kind == "set_account_state":
            parsed_state = SetAccountStateCommand.model_validate(raw_with_reason)
            target = await self._require_target_user(
                parsed_state.target_user_id,
                parsed_state.expected_user_revision,
                include_active_directors=not parsed_state.active,
            )
            if target.is_active == parsed_state.active:
                raise _stale()
            if (
                not parsed_state.active
                and target.role in COMPANY_RESOURCE_ROLES
                and not await self.users.has_other_usable_director(target.id)
            ):
                raise AppException(
                    "At least one other director account must be able to sign in.",
                    status_code=409,
                    error_code="LAST_ACCESS_MANAGER_REQUIRED",
                )
            target.is_active = parsed_state.active
            target.access_revision += 1
            target.updated_at = now
            await self.auth.revoke_user_authentication(target.id)
            await self._close_business_streams(target.id, now)
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "is_active": target.is_active,
                "access_revision": target.access_revision,
                "sessions_revoked": True,
            }
            return None

        if kind == "unlock_account":
            parsed_unlock = UnlockAccountCommand.model_validate(raw_with_reason)
            target = await self._require_target_user(
                parsed_unlock.target_user_id, parsed_unlock.expected_user_revision
            )
            if target.failed_login_attempts == 0 and (
                target.locked_until is None or target.locked_until <= now
            ):
                raise _stale()
            target.failed_login_attempts = 0
            target.locked_until = None
            target.updated_at = now
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "locked": False,
                "access_revision": target.access_revision,
            }
            return None

        if kind == "change_business_role":
            parsed_role = ChangeBusinessRoleCommand.model_validate(raw_with_reason)
            new_role = validate_role(parsed_role.new_role)
            if new_role not in BUSINESS_ROLES:
                raise _denied()
            target = await self._require_target_user(
                parsed_role.target_user_id,
                parsed_role.expected_user_revision,
                include_active_directors=True,
            )
            if target.role == new_role:
                raise _stale()
            if (
                target.is_active
                and target.role in COMPANY_RESOURCE_ROLES
                and new_role not in COMPANY_RESOURCE_ROLES
                and not await self.users.has_other_usable_director(target.id)
            ):
                raise AppException(
                    "At least one other director account must be able to sign in.",
                    status_code=409,
                    error_code="LAST_ACCESS_MANAGER_REQUIRED",
                )
            previous_role = target.role
            target.role = new_role
            target.access_revision += 1
            target.updated_at = now
            await self.auth.revoke_user_authentication(target.id)
            await self._close_business_streams(target.id, now)
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "previous_role": previous_role,
                "new_role": target.role,
                "access_revision": target.access_revision,
                "sessions_revoked": True,
            }
            return None

        if kind == "change_project_membership":
            parsed_mem = ChangeProjectMembershipCommand.model_validate(raw_with_reason)
            target = await self._require_target_user(
                parsed_mem.target_user_id, parsed_mem.expected_user_revision
            )
            project = await self.session.get(
                Project, parsed_mem.project_id, with_for_update=True
            )
            if (
                project is None
                or project.deleted_at is not None
                or project.status in READ_ONLY_STATUSES
                or project.revision != parsed_mem.expected_project_revision
            ):
                raise _stale("The target project changed or is read-only.")
            existing_member = await self.session.scalar(
                select(ProjectMember)
                .where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.user_id == target.id,
                    ProjectMember.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if parsed_mem.action == "assign":
                if not target.is_active or existing_member is not None:
                    raise _stale("Target user is inactive or already assigned to this project.")
                linked_emp = await self.session.scalar(
                    select(HrEmployee).where(HrEmployee.user_id == target.id)
                )
                if linked_emp is not None and (
                    linked_emp.deleted_at is not None
                    or linked_emp.employment_status not in ACTIVE_ASSIGNMENT_EMPLOYMENT
                ):
                    raise _stale("Linked employee record is no longer eligible for assignment.")
                self.session.add(
                    ProjectMember(
                        project_id=project.id,
                        user_id=target.id,
                        role_in_project=parsed_mem.role_in_project or None,
                    )
                )
            else:
                if existing_member is None:
                    raise _stale("Project membership was already removed.")
                existing_member.deleted_at = now
            project.revision += 1
            target.access_revision += 1
            target.updated_at = now
            await self.session.flush()
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "project_id": str(project.id),
                "project_code": project.code,
                "action": parsed_mem.action,
                "project_revision": project.revision,
                "access_revision": target.access_revision,
            }
            return None

        if kind == "request_account_recovery":
            parsed_rec = RequestAccountRecoveryCommand.model_validate(raw_with_reason)
            await self._verify_live_preconditions(ctx, command)
            target = await self._require_target_user(
                parsed_rec.target_user_id, parsed_rec.expected_user_revision
            )
            if not target.is_active:
                raise _stale()
            target.access_revision += 1
            target.updated_at = now
            await self.auth.revoke_user_authentication(target.id)
            await self._close_business_streams(target.id, now)
            settings = get_settings()
            otp = generate_otp()
            challenge = await self.auth.add_otp_challenge(
                AuthOtpChallenge(
                    id=uuid4(),
                    user_id=target.id,
                    purpose="password_reset",
                    otp_hash=hash_secret(otp),
                    expires_at=now
                    + timedelta(minutes=min(10, settings.otp_expire_minutes)),
                )
            )
            command.status = "delivery_pending"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "access_revision": target.access_revision,
                "delivery_state": "pending",
                "reset_state": "waiting",
                "destination_masked": _masked_email(target.email),
            }
            return {
                "kind": "recovery",
                "recipient": target.email,
                "full_name": target.full_name,
                "otp": otp,
                "challenge_id": challenge.id,
            }

        if kind == "revoke_business_session":
            parsed_sess = RevokeBusinessSessionCommand.model_validate(raw_with_reason)
            target = await self._require_target_user(
                parsed_sess.target_user_id, parsed_sess.expected_user_revision
            )
            if parsed_sess.scope == "selected":
                assert parsed_sess.session_id is not None
                auth_session = await self.session.get(
                    AuthSession, parsed_sess.session_id, with_for_update=True
                )
                if auth_session is None or auth_session.user_id != target.id:
                    raise NotFoundException("Business session")
                if auth_session.revoked_at is not None:
                    raise _stale("The selected session was already revoked.")
                auth_session.revoked_at = now
                await self.session.execute(
                    update(AuthRefreshToken)
                    .where(
                        AuthRefreshToken.user_id == target.id,
                        AuthRefreshToken.session_id == auth_session.id,
                        AuthRefreshToken.revoked_at.is_(None),
                        AuthRefreshToken.deleted_at.is_(None),
                    )
                    .values(revoked_at=now)
                )
                command.status = "succeeded"
                command.completed_at = now
                command.result_json = {
                    "user_id": str(target.id),
                    "scope": "selected",
                    "revoked_session_id": str(auth_session.id),
                    "access_revision": target.access_revision,
                }
                return None

            target.access_revision += 1
            target.updated_at = now
            await self.auth.revoke_user_authentication(target.id)
            await self._close_business_streams(target.id, now)
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "user_id": str(target.id),
                "scope": "all",
                "access_revision": target.access_revision,
            }
            return None

        if kind == "update_safe_setting":
            parsed_set = UpdateSafeSettingCommand.model_validate(raw_with_reason)
            cleaned_val = validate_safe_setting_value(
                parsed_set.setting_key, parsed_set.value
            )
            stored = await self.session.get(
                SupportSafeSetting, parsed_set.setting_key, with_for_update=True
            )
            current_rev = stored.revision if stored is not None else 0
            if current_rev != parsed_set.expected_revision:
                raise _stale("The setting revision changed before execution.")
            new_rev = current_rev + 1
            if stored is None:
                self.session.add(
                    SupportSafeSetting(
                        key=parsed_set.setting_key,
                        value_json={"value": cleaned_val},
                        revision=new_rev,
                        updated_by_operator_id=ctx.operator_id,
                        updated_by_command_id=command.id,
                        updated_at=now,
                    )
                )
            else:
                stored.value_json = {"value": cleaned_val}
                stored.revision = new_rev
                stored.updated_by_operator_id = ctx.operator_id
                stored.updated_by_command_id = command.id
                stored.updated_at = now
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "setting_key": parsed_set.setting_key,
                "value": cleaned_val,
                "revision": new_rev,
                "effect": SAFE_SETTINGS_REGISTRY[parsed_set.setting_key].effect,
            }
            return None

        if kind == "retry_safe_job":
            parsed_job = RetrySafeJobCommand.model_validate(raw_with_reason)
            await self._validate_retryable_job(parsed_job.job_source, parsed_job.job_id)
            if parsed_job.job_source == "task_outbox":
                entry = await self.session.get(
                    TaskOutbox, parsed_job.job_id, with_for_update=True
                )
                assert entry is not None
                entry.status = "pending"
                entry.attempts = min(entry.attempts, MAX_OUTBOX_ATTEMPTS - 1)
                if entry.task_name == "run_import_async" and entry.args_json:
                    batch_id = UUID(str(entry.args_json[0]))
                    batch = await self.session.get(
                        ImportBatch, batch_id, with_for_update=True
                    )
                    if batch is not None and batch.status == "failed":
                        batch.status = "queued"
            else:
                delivery = await self.session.get(
                    SupportRecoveryDelivery, parsed_job.job_id, with_for_update=True
                )
                assert delivery is not None
                delivery.status = "pending"
                delivery.dispatch_started_at = None
                delivery.dispatch_finished_at = None
            command.status = "succeeded"
            command.completed_at = now
            command.result_json = {
                "job_source": parsed_job.job_source,
                "job_id": str(parsed_job.job_id),
                "status": "pending",
            }
            return None

        if kind == "bulk_account_lifecycle":
            parsed_bulk = BulkAccountLifecycleCommand.model_validate(raw_with_reason)
            await self._execute_bulk_lifecycle(parsed_bulk, command, now)
            return None

        raise _denied()

    async def _execute_bulk_lifecycle(
        self,
        payload: BulkAccountLifecycleCommand,
        command: SupportAdminCommand,
        now: datetime,
    ) -> None:
        target_ids = [item.user_id for item in payload.targets]
        expected_map = {item.user_id: item.expected_user_revision for item in payload.targets}
        locked = await self.users.lock_users(
            *target_ids, include_active_directors=(payload.operation == "disable")
        )
        outcomes: list[dict[str, Any]] = []
        succeeded_count = 0
        for uid in target_ids:
            user = locked.get(uid)
            if (
                user is None
                or user.deleted_at is not None
                or user.role not in BUSINESS_ROLES
                or user.access_revision != expected_map[uid]
            ):
                outcomes.append({"user_id": str(uid), "outcome": "skipped_stale"})
                continue
            if payload.operation == "disable":
                if not user.is_active:
                    outcomes.append({"user_id": str(uid), "outcome": "skipped_stale"})
                    continue
                if (
                    user.role in COMPANY_RESOURCE_ROLES
                    and not await self.users.has_other_usable_director(user.id)
                ):
                    outcomes.append(
                        {
                            "user_id": str(uid),
                            "outcome": "denied_last_director",
                        }
                    )
                    continue
                user.is_active = False
                user.access_revision += 1
                user.updated_at = now
                await self.auth.revoke_user_authentication(user.id)
                await self._close_business_streams(user.id, now)
                succeeded_count += 1
                outcomes.append(
                    {
                        "user_id": str(user.id),
                        "outcome": "succeeded",
                        "access_revision": user.access_revision,
                    }
                )
            elif payload.operation == "reactivate":
                if user.is_active:
                    outcomes.append({"user_id": str(uid), "outcome": "skipped_stale"})
                    continue
                user.is_active = True
                user.access_revision += 1
                user.updated_at = now
                await self.auth.revoke_user_authentication(user.id)
                succeeded_count += 1
                outcomes.append(
                    {
                        "user_id": str(user.id),
                        "outcome": "succeeded",
                        "access_revision": user.access_revision,
                    }
                )
            elif payload.operation == "unlock":
                is_locked = bool(user.locked_until is not None and user.locked_until > now)
                if user.failed_login_attempts == 0 and not is_locked:
                    outcomes.append({"user_id": str(uid), "outcome": "skipped_stale"})
                    continue
                user.failed_login_attempts = 0
                user.locked_until = None
                user.updated_at = now
                succeeded_count += 1
                outcomes.append(
                    {
                        "user_id": str(user.id),
                        "outcome": "succeeded",
                        "access_revision": user.access_revision,
                    }
                )
            elif payload.operation == "revoke_sessions":
                user.access_revision += 1
                user.updated_at = now
                await self.auth.revoke_user_authentication(user.id)
                await self._close_business_streams(user.id, now)
                succeeded_count += 1
                outcomes.append(
                    {
                        "user_id": str(user.id),
                        "outcome": "succeeded",
                        "access_revision": user.access_revision,
                    }
                )
        command.status = "succeeded"
        command.completed_at = now
        command.result_json = {
            "operation": payload.operation,
            "succeeded_count": succeeded_count,
            "total_count": len(target_ids),
            "items": outcomes,
        }
        return None

    async def _close_business_streams(self, user_id: UUID, now: datetime) -> None:
        await self.session.execute(
            update(BusinessLogStream)
            .where(
                BusinessLogStream.user_id == user_id,
                BusinessLogStream.closed_at.is_(None),
            )
            .values(closed_at=now)
        )

    async def _deliver_post_commit_mail(
        self,
        command_id: UUID,
        actor_id: UUID,
        request_id: str,
        mail_info: dict[str, Any],
    ) -> None:
        settings = get_settings()
        recipient = str(mail_info["recipient"])
        otp = str(mail_info["otp"])
        if mail_info["kind"] == "invitation":
            subject = "Your Garrisons Portal Account Invitation"
            body = (
                f"Hello {mail_info['full_name']},\n\n"
                "An account has been created for you on the Garrisons Portal.\n"
                f"Use this one-time password setup code to activate your password: {otp}\n\n"
                f"This code expires in {settings.otp_expire_minutes} minutes."
            )
        else:
            subject = "Your Garrisons Account Recovery Instructions"
            body = (
                f"Hello {mail_info['full_name']},\n\n"
                f"Your one-time password recovery code is: {otp}\n\n"
                f"This code expires in {min(10, settings.otp_expire_minutes)} minutes."
            )
        accepted = False
        try:
            sent = await asyncio.to_thread(
                EmailService().send,
                recipients=[recipient],
                subject=subject,
                body=body,
            )
            accepted = sent > 0
        except EmailDeliveryError:
            accepted = False

        command = await self.session.get(SupportAdminCommand, command_id, with_for_update=True)
        if command is not None and command.status == "delivery_pending":
            result = dict(command.result_json or {})
            if mail_info["kind"] == "invitation":
                result["invitation_state"] = "accepted" if accepted else "failed"
            else:
                result["delivery_state"] = "accepted" if accepted else "failed"
                result["reset_state"] = "ready" if accepted else "unavailable"
            if not accepted:
                challenge_id = mail_info.get("challenge_id")
                if isinstance(challenge_id, UUID):
                    challenge = await self.session.get(
                        AuthOtpChallenge, challenge_id, with_for_update=True
                    )
                    if challenge is not None and challenge.consumed_at is None:
                        challenge.consumed_at = utc_now()
            command.status = "succeeded" if accepted else "delivery_failed"
            command.result_json = result
            self._audit(command.id, actor_id, "delivery_updated", request_id)
            await self.session.commit()
