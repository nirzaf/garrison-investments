"""Typed technical actor context, explicit command policy matrix, and safe settings registry."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from hmac import compare_digest
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.support_admin_commands import ALLOWLISTED_SAFE_SETTING_KEYS, SupportSafeSetting
from app.models.support_cases import SupportOperatorGrant
from app.models.support_identity import (
    SupportAuthEvent,
    SupportCredential,
    SupportOperator,
    SupportSession,
)
from app.models.support_registration import SupportBootstrap
from app.schemas.support_company_admin import (
    SupportCompanyContextRead,
    SupportCredentialSummary,
    SupportFeatureAvailability,
    SupportOwnerAuthEventItem,
    SupportOwnerSecurityRead,
    SupportSafeSettingItem,
    SupportSafeSettingsRead,
)
from app.services.support_identity import SupportIdentity, _digest, support_session_deadline
from app.services.support_overview import execute_oversight_read
from app.utils.exceptions import AppException, PermissionDeniedException
from app.utils.security import utc_now

POLICY_VERSION = "2026-11-v1"
_GIT_SHA_RE = re.compile(r"^[a-f0-9]{40}$")


@dataclass(frozen=True)
class CommandPolicyRule:
    command_kind: str
    label: str
    required_capability: str
    requires_action_passkey: bool
    allows_protected_targets_solo: bool
    protected_target_note: str


TECHNICAL_COMMAND_POLICY: dict[str, CommandPolicyRule] = {
    "create_business_account": CommandPolicyRule(
        command_kind="create_business_account",
        label="Create and invite business user",
        required_capability="company.accounts.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note=(
            "Account creation enforces the fixed business-role ceiling and delivers "
            "one-time recovery material directly to the verified recipient."
        ),
    ),
    "set_account_state": CommandPolicyRule(
        command_kind="set_account_state",
        label="Enable or disable business sign-in",
        required_capability="company.accounts.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note=(
            "Disabling a director requires at least one other active, unlocked director account."
        ),
    ),
    "unlock_account": CommandPolicyRule(
        command_kind="unlock_account",
        label="Clear failed sign-in lock",
        required_capability="company.accounts.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note="Clears temporary failed-login lockout without altering passwords.",
    ),
    "change_business_role": CommandPolicyRule(
        command_kind="change_business_role",
        label="Change business role",
        required_capability="company.access.assign",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note=(
            "Assigns only supported business roles, increments access_revision, revokes "
            "sessions, and preserves the last-usable-director invariant."
        ),
    ),
    "change_project_membership": CommandPolicyRule(
        command_kind="change_project_membership",
        label="Assign or revoke project membership",
        required_capability="company.access.assign",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note=(
            "Requires an editable project and eligible active account; increments "
            "project revision and target access_revision."
        ),
    ),
    "request_account_recovery": CommandPolicyRule(
        command_kind="request_account_recovery",
        label="Send recipient-mediated recovery instructions",
        required_capability="company.accounts.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=False,
        protected_target_note=(
            "Protected director and HR Manager accounts cannot be recovered via a solo "
            "owner session; use paired custody or an offline recovery ceremony."
        ),
    ),
    "revoke_business_session": CommandPolicyRule(
        command_kind="revoke_business_session",
        label="Revoke selected or all business sessions",
        required_capability="company.sessions.revoke",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note="Revokes selected session or all active sessions and challenges.",
    ),
    "update_safe_setting": CommandPolicyRule(
        command_kind="update_safe_setting",
        label="Update allowlisted operational setting",
        required_capability="company.settings.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note="Applies only to registered non-secret operational display settings.",
    ),
    "retry_safe_job": CommandPolicyRule(
        command_kind="retry_safe_job",
        label="Retry eligible terminal outbox or recovery job",
        required_capability="company.jobs.retry",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note="Re-queues only terminal failed/unknown jobs with original payload.",
    ),
    "bulk_account_lifecycle": CommandPolicyRule(
        command_kind="bulk_account_lifecycle",
        label="Execute bounded bulk account lifecycle operation",
        required_capability="company.accounts.manage",
        requires_action_passkey=True,
        allows_protected_targets_solo=True,
        protected_target_note="Validates up to 25 explicit accounts with per-item anti-lockout.",
    ),
}


@dataclass(frozen=True)
class SafeSettingSpec:
    key: str
    label: str
    description: str
    value_type: Literal["string", "integer"]
    default_value: str | int
    effect: Literal["immediate", "restart_required"]
    min_value: int | None = None
    max_value: int | None = None
    max_length: int = 240


SAFE_SETTINGS_REGISTRY: dict[str, SafeSettingSpec] = {
    "company_display_name": SafeSettingSpec(
        key="company_display_name",
        label="Company display name",
        description="Name displayed in the Company Control Centre header.",
        value_type="string",
        default_value="Garrisons Investments",
        effect="immediate",
        max_length=120,
    ),
    "support_banner_notice": SafeSettingSpec(
        key="support_banner_notice",
        label="Control centre operational notice",
        description="Non-secret operational banner shown across technical pages.",
        value_type="string",
        default_value="",
        effect="immediate",
        max_length=240,
    ),
    "default_directory_page_size": SafeSettingSpec(
        key="default_directory_page_size",
        label="Default directory page size",
        description="Default page size for the People & Access account directory (10-100).",
        value_type="integer",
        default_value=25,
        effect="immediate",
        min_value=10,
        max_value=100,
    ),
    "maintenance_window_notice": SafeSettingSpec(
        key="maintenance_window_notice",
        label="Planned maintenance notice",
        description="Optional advisory notice for scheduled maintenance windows.",
        value_type="string",
        default_value="",
        effect="immediate",
        max_length=240,
    ),
}

PERMANENTLY_LOCKED_CONTROLS: tuple[str, ...] = (
    "LOG_PURGE_ENABLED (permanently false; retain-only audit mode)",
    "JWT signing keys, HR encryption keys, and backup encryption secrets",
    "Database connection URL, Redis broker URL, and S3/MinIO credentials",
    "Support custody mode and technical OTP recipient mailbox bindings",
    "TLS certificate paths, trusted ingress peer, and host incident holds",
    "Finance invoice/payment write policy and payroll dual-approval policy",
)


@dataclass(frozen=True)
class SupportActorContext:
    """Explicit technical actor identity; never converted into a business User."""

    operator_id: UUID
    display_label: str
    session_id: UUID
    grant_epoch: int
    auth_method: Literal["passkey", "email_otp_only"]
    authorization_mode: Literal["single_owner", "paired"]
    capabilities: frozenset[str]
    request_id: str
    session_expires_at: datetime


async def resolve_support_actor_context(
    session: AsyncSession,
    token: str | None,
    csrf: str | None = None,
    *,
    request_id: str,
    required_capability: str | None = None,
    require_csrf: bool = False,
    require_passkey_assurance: bool = False,
) -> tuple[SupportActorContext, SupportOperator, SupportSession]:
    identity = SupportIdentity(session)
    operator, active = await identity.current(
        token, require_passkey_assurance=require_passkey_assurance
    )
    if require_csrf and (
        not csrf or len(csrf) != 43 or not compare_digest(active.csrf_hash, _digest(csrf))
    ):
        raise AppException(
            "Support request could not be verified.",
            status_code=403,
            error_code="SUPPORT_CSRF_INVALID",
        )
    grants = set(
        await session.scalars(
            select(SupportOperatorGrant.capability).where(
                SupportOperatorGrant.operator_id == operator.id
            )
        )
    )
    if required_capability is not None and required_capability not in grants:
        raise PermissionDeniedException(required_capability)
    is_owner = await identity.is_single_owner(operator.id)
    auth_method: Literal["passkey", "email_otp_only"] = (
        "email_otp_only" if active.auth_method == "email_otp_only" else "passkey"
    )
    ctx = SupportActorContext(
        operator_id=operator.id,
        display_label=operator.display_label,
        session_id=active.id,
        grant_epoch=operator.grant_epoch,
        auth_method=auth_method,
        authorization_mode="single_owner" if is_owner else "paired",
        capabilities=frozenset(grants),
        request_id=request_id,
        session_expires_at=active.expires_at,
    )
    return ctx, operator, active


def validate_safe_setting_value(key: str, raw_value: str | int) -> str | int:
    if key not in ALLOWLISTED_SAFE_SETTING_KEYS or key not in SAFE_SETTINGS_REGISTRY:
        raise AppException(
            "Only registered non-secret operational settings can be modified.",
            status_code=422,
            error_code="SUPPORT_SETTING_NOT_ALLOWLISTED",
        )
    spec = SAFE_SETTINGS_REGISTRY[key]
    if spec.value_type == "integer":
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise AppException(
                f"Setting '{key}' requires an integer value.",
                status_code=422,
                error_code="SUPPORT_SETTING_INVALID_VALUE",
            )
        if (spec.min_value is not None and raw_value < spec.min_value) or (
            spec.max_value is not None and raw_value > spec.max_value
        ):
            raise AppException(
                f"Setting '{key}' must be between {spec.min_value} and {spec.max_value}.",
                status_code=422,
                error_code="SUPPORT_SETTING_OUT_OF_RANGE",
            )
        return raw_value
    if not isinstance(raw_value, str):
        raise AppException(
            f"Setting '{key}' requires a text value.",
            status_code=422,
            error_code="SUPPORT_SETTING_INVALID_VALUE",
        )
    cleaned = raw_value.strip()
    if len(cleaned) > spec.max_length:
        raise AppException(
            f"Setting '{key}' exceeds maximum length ({spec.max_length}).",
            status_code=422,
            error_code="SUPPORT_SETTING_OUT_OF_RANGE",
        )
    if key == "company_display_name" and len(cleaned) < 2:
        raise AppException(
            "Company display name must be at least 2 characters.",
            status_code=422,
            error_code="SUPPORT_SETTING_INVALID_VALUE",
        )
    return cleaned


async def load_safe_setting_items(session: AsyncSession) -> list[SupportSafeSettingItem]:
    rows = {
        row.key: row
        for row in await session.scalars(
            select(SupportSafeSetting).order_by(SupportSafeSetting.key)
        )
    }
    items: list[SupportSafeSettingItem] = []
    for key, spec in SAFE_SETTINGS_REGISTRY.items():
        stored = rows.get(key)
        current_val = (
            stored.value_json.get("value", spec.default_value)
            if stored is not None and isinstance(stored.value_json, dict)
            else spec.default_value
        )
        items.append(
            SupportSafeSettingItem(
                key=key,
                label=spec.label,
                description=spec.description,
                value_type=spec.value_type,
                current_value=current_val,
                default_value=spec.default_value,
                revision=stored.revision if stored is not None else 0,
                effect=spec.effect,
                updated_at=stored.updated_at if stored is not None else None,
                updated_by_operator_id=(
                    stored.updated_by_operator_id if stored is not None else None
                ),
            )
        )
    return items


async def read_company_context(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportCompanyContextRead:
    ctx, _, active = await resolve_support_actor_context(
        session, token, request_id=request_id
    )
    settings = get_settings()
    raw_sha = os.environ.get("APP_COMMIT_SHA", "").strip().lower()
    source_sha = raw_sha if _GIT_SHA_RE.fullmatch(raw_sha) else "unknown"
    bootstrap = await session.get(SupportBootstrap, 1)
    if bootstrap is not None and bootstrap.custody_mode in ("single_owner", "paired"):
        custody_mode: Literal["single_owner", "paired", "unknown"] = bootstrap.custody_mode  # type: ignore[assignment]
    elif settings.support_custody_mode in ("single_owner", "paired"):
        custody_mode = settings.support_custody_mode
    else:
        custody_mode = "unknown"

    safe_items = {item.key: item.current_value for item in await load_safe_setting_items(session)}
    caps = ctx.capabilities

    def _cap_feature(
        key: str, label: str, cap: str, enabled_reason: str
    ) -> SupportFeatureAvailability:
        has_cap = cap in caps
        return SupportFeatureAvailability(
            key=key,
            label=label,
            enabled=has_cap,
            required_capability=cap,
            reason=enabled_reason
            if has_cap
            else f"Missing operator capability '{cap}'.",
        )

    features = [
        _cap_feature(
            "people_directory",
            "People & Access directory",
            "company.directory.read",
            "Paginated business account summary and User 360 profile enabled.",
        ),
        _cap_feature(
            "account_lifecycle",
            "Account creation, lock handling, and recovery",
            "company.accounts.manage",
            "Guided account creation, state change, unlock, and recovery commands enabled.",
        ),
        _cap_feature(
            "access_assignment",
            "Business role and project membership commands",
            "company.access.assign",
            "Role ceiling and revision-bound project membership commands enabled.",
        ),
        _cap_feature(
            "session_inventory",
            "Business session inventory",
            "company.sessions.read",
            "Per-user session metadata inspection enabled.",
        ),
        _cap_feature(
            "session_revocation",
            "Targeted and all-session revocation",
            "company.sessions.revoke",
            "Selected-session and all-session revocation commands enabled.",
        ),
        _cap_feature(
            "safe_settings",
            "Allowlisted operational settings editor",
            "company.settings.manage",
            "Audited updates for allowlisted non-secret settings enabled.",
        ),
        _cap_feature(
            "safe_job_retry",
            "Allowlisted terminal job retry",
            "company.jobs.retry",
            "Retry commands for terminal failed outbox and recovery jobs enabled.",
        ),
        _cap_feature(
            "data_inspector",
            "Registered non-sensitive data inspector",
            "company.data.inspect",
            "Read-only allowlisted entity inspection enabled.",
        ),
        SupportFeatureAvailability(
            key="finance_invoice_writes",
            label="Invoice creation, approval, and payment execution",
            enabled=False,
            required_capability=None,
            reason=(
                "Disabled by business policy. Technical ownership never grants "
                "accounting authority."
            ),
        ),
        SupportFeatureAvailability(
            key="payroll_execution",
            label="Payroll run preparation, approval, and settlement",
            enabled=False,
            required_capability=None,
            reason=(
                "Disabled by business policy. Payroll remains gated to independent "
                "business operators."
            ),
        ),
        SupportFeatureAvailability(
            key="confidential_hr_vault",
            label="Confidential HR salary, medical, and employee-relations records",
            enabled=False,
            required_capability=None,
            reason=(
                "Blocked in technical portal. Only non-sensitive account linkage "
                "status is visible."
            ),
        ),
        SupportFeatureAvailability(
            key="production_restore_trigger",
            label="Browser-triggered production restore",
            enabled=False,
            required_capability=None,
            reason=(
                "Blocked by recovery policy. Production restore requires host-level "
                "maintenance authority."
            ),
        ),
    ]
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    active.last_seen_at = now
    await session.commit()
    return SupportCompanyContextRead(
        company_name=str(safe_items.get("company_display_name", "Garrisons Investments")),
        deployment_scope="single_company",
        environment=settings.app_env.strip().lower() or "unknown",
        source_sha=source_sha,
        custody_mode=custody_mode,
        auth_method=ctx.auth_method,
        operator_id=ctx.operator_id,
        session_expires_at=ctx.session_expires_at,
        capabilities=sorted(caps),
        banner_notice=str(safe_items.get("support_banner_notice", "")),
        maintenance_window_notice=str(safe_items.get("maintenance_window_notice", "")),
        default_directory_page_size=int(safe_items.get("default_directory_page_size", 25)),
        policy_version=POLICY_VERSION,
        features=features,
        observed_at=now,
    )


async def read_safe_settings(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportSafeSettingsRead:
    ctx, _, _ = await resolve_support_actor_context(
        session, token, request_id=request_id
    )
    if "config.read" not in ctx.capabilities and "company.settings.manage" not in ctx.capabilities:
        raise PermissionDeniedException("config.read")
    capability = (
        "company.settings.manage"
        if "company.settings.manage" in ctx.capabilities
        else "config.read"
    )
    editable = "company.settings.manage" in ctx.capabilities

    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportSafeSettingsRead:
        items = await load_safe_setting_items(db)
        return SupportSafeSettingsRead(
            observed_at=now,
            editable_enabled=editable,
            items=items,
            permanently_locked_controls=list(PERMANENTLY_LOCKED_CONTROLS),
        )

    def degraded(now: datetime) -> SupportSafeSettingsRead:
        return SupportSafeSettingsRead(
            observed_at=now,
            editable_enabled=False,
            items=[],
            permanently_locked_controls=list(PERMANENTLY_LOCKED_CONTROLS),
        )

    return await execute_oversight_read(
        session,
        token,
        capability=capability,
        surface="company_settings",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_owner_security(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportOwnerSecurityRead:
    ctx, operator, active = await resolve_support_actor_context(
        session, token, request_id=request_id
    )
    bootstrap = await session.get(SupportBootstrap, 1)
    credentials = list(
        await session.scalars(
            select(SupportCredential)
            .where(SupportCredential.operator_id == operator.id)
            .order_by(SupportCredential.created_at.asc(), SupportCredential.id.asc())
        )
    )
    active_count = sum(1 for cred in credentials if cred.revoked_at is None)
    events = list(
        await session.scalars(
            select(SupportAuthEvent)
            .where(SupportAuthEvent.operator_id == operator.id)
            .order_by(SupportAuthEvent.occurred_at.desc(), SupportAuthEvent.id.desc())
            .limit(20)
        )
    )
    now = utc_now()
    if support_session_deadline(active) <= now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    active.last_seen_at = now
    await session.commit()
    return SupportOwnerSecurityRead(
        operator_id=operator.id,
        display_label=operator.display_label,
        status=operator.status,
        grant_epoch=operator.grant_epoch,
        custody_mode=(
            bootstrap.custody_mode  # type: ignore[arg-type]
            if bootstrap is not None and bootstrap.custody_mode in ("single_owner", "paired")
            else ctx.authorization_mode
        ),
        bootstrap_activated_at=bootstrap.activated_at if bootstrap is not None else None,
        session_id=active.id,
        session_auth_method=ctx.auth_method,
        session_expires_at=active.expires_at,
        session_idle_deadline=support_session_deadline(active),
        active_passkey_count=active_count,
        minimum_passkeys_required=2,
        passkeys=[
            SupportCredentialSummary(
                credential_id=cred.id,
                credential_hash_prefix=cred.credential_hash[:12],
                sign_count=cred.sign_count,
                created_at=cred.created_at,
                revoked_at=cred.revoked_at,
                status="active" if cred.revoked_at is None else "revoked",
            )
            for cred in credentials
        ],
        recent_auth_events=[
            SupportOwnerAuthEventItem(
                id=ev.id,
                action=ev.action,
                request_id=ev.request_id,
                occurred_at=ev.occurred_at,
            )
            for ev in events
        ],
        recovery_guidance=[
            (
                "Maintain at least two distinct enrolled hardware or device-bound "
                "passkeys at all times."
            ),
            (
                "Every administrative mutation requires an action-bound passkey proof "
                "in the planning session."
            ),
            (
                "Converting between single-owner and paired custody cannot be performed "
                "via a config flag; historical bootstrap evidence is immutable."
            ),
            (
                "If all owner passkeys are lost, use the offline host recovery ceremony "
                "with a signed private approval file."
            ),
        ],
    )
