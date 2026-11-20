from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
     BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    model_validator,
)

from app.utils.permissions import BUSINESS_ROLES

CommandReasonCode = Literal[
    "account_provisioning",
    "role_adjustment",
    "project_membership",
    "suspected_access",
    "verified_user_report",
    "failed_sign_in",
    "offboarding_access",
    "operational_configuration",
    "operational_recovery",
]

SupportAccessDenialCategory = Literal[
    "allowed",
    "no_permission",
    "no_project_membership",
    "account_inactive",
    "not_eligible_approver",
    "self_approval_prohibited",
    "feature_disabled_by_policy",
]

CommandStatus = Literal[
    "planned",
    "expired",
    "succeeded",
    "delivery_pending",
    "delivery_failed",
    "rejected",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SupportFeatureAvailability(BaseModel):
    key: str
    label: str
    enabled: bool
    required_capability: str | None = None
    reason: str


class SupportCompanyContextRead(BaseModel):
    company_name: str
    deployment_scope: Literal["single_company"] = "single_company"
    environment: str
    source_sha: str
    custody_mode: Literal["single_owner", "paired", "unknown"]
    auth_method: Literal["passkey", "email_otp_only"]
    operator_id: UUID
    session_expires_at: datetime
    capabilities: list[str]
    banner_notice: str
    maintenance_window_notice: str
    default_directory_page_size: int
    policy_version: str
    features: list[SupportFeatureAvailability]
    observed_at: datetime


class SupportCompanyUserSummary(BaseModel):
    user_id: UUID
    full_name: str
    email_masked: str
    employee_code: str | None
    designation: str | None
    role: str
    role_label: str
    state: Literal["active", "inactive", "locked"]
    is_active: bool
    is_locked: bool
    access_revision: int
    assigned_project_count: int
    has_linked_employee: bool
    recovery_destination_verified: bool
    last_login_at: datetime | None


class SupportCompanyUserPage(BaseModel):
    items: list[SupportCompanyUserSummary]
    total: int
    next_cursor: str | None = None


class SupportUserActionAvailability(BaseModel):
    action_kind: str
    label: str
    allowed: bool
    required_capability: str
    reason: str


class SupportLinkedCaseSummary(BaseModel):
    case_id: UUID
    external_ref: str | None
    status: str
    severity: str | None
    reason_code: str | None
    revision: int


class SupportCompanyUserProfileRead(BaseModel):
    user_id: UUID
    full_name: str
    email_masked: str
    employee_code: str | None
    phone_masked: str | None
    designation: str | None
    role: str
    role_label: str
    state: Literal["active", "inactive", "locked"]
    is_active: bool
    is_locked: bool
    must_change_password: bool
    access_revision: int
    recovery_destination_verified: bool
    has_linked_employee: bool
    employee_status: str | None
    assigned_project_count: int
    active_session_count: int
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    available_actions: list[SupportUserActionAvailability]
    linked_cases: list[SupportLinkedCaseSummary]


class SupportRoleOption(BaseModel):
    role: str
    label: str
    permissions: list[str]
    company_scope: bool
    protected_target: bool


class SupportUserProjectMembershipRead(BaseModel):
    membership_id: UUID
    project_id: UUID
    project_code: str
    project_name: str
    project_status: str
    project_revision: int
    role_in_project: str | None


class SupportProjectOptionRead(BaseModel):
    project_id: UUID
    project_code: str
    project_name: str
    project_status: str
    project_revision: int
    is_member: bool
    is_read_only: bool


class SupportAccessExplanationItem(BaseModel):
    subject_key: str
    label: str
    allowed: bool
    category: SupportAccessDenialCategory
    explanation: str


class SupportNavigationRouteItem(BaseModel):
    route_id: str
    visible: bool


class SupportCompanyUserAccessRead(BaseModel):
    user_id: UUID
    role: str
    role_label: str
    access_revision: int
    is_active: bool
    company_scope: bool
    effective_permissions: list[str]
    assignable_roles: list[SupportRoleOption]
    project_memberships: list[SupportUserProjectMembershipRead]
    eligible_projects: list[SupportProjectOptionRead]
    navigation_routes: list[SupportNavigationRouteItem]
    explanations: list[SupportAccessExplanationItem]
    focused_project_explanation: SupportAccessExplanationItem | None = None


class SupportUserSessionItem(BaseModel):
    session_id: UUID
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    state: Literal["active", "revoked", "expired"]
    active_refresh_tokens: int


class SupportUserSessionInventoryRead(BaseModel):
    user_id: UUID
    access_revision: int
    has_unindexed_legacy_tokens: bool
    active_session_count: int
    sessions: list[SupportUserSessionItem]


class SupportUserActivityItem(BaseModel):
    event_id: UUID
    source: Literal["business_auth", "technical_command", "case_account_action"]
    category: str
    summary: str
    actor_reference: str | None
    authorization_mode: str | None
    occurred_at: datetime


class SupportUserActivityPage(BaseModel):
    user_id: UUID
    items: list[SupportUserActivityItem]


class SupportDiagnoseCaseRequest(_StrictModel):
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]
    project_id: UUID | None = None


class SupportDiagnoseCaseRead(BaseModel):
    case_id: UUID
    external_ref: str | None
    status: str
    revision: int
    subject_user_id: UUID
    linked_project_ids: list[UUID]
    created_new: bool


class ProjectAssignmentSpec(_StrictModel):
    project_id: UUID
    expected_project_revision: Annotated[int, Field(ge=1)]
    role_in_project: Annotated[str | None, Field(default=None, max_length=100)] = None


class CreateBusinessAccountCommand(_StrictModel):
    command_kind: Literal["create_business_account"]
    email: EmailStr
    full_name: Annotated[str, StringConstraints(min_length=2, max_length=120)]
    role: Annotated[str, StringConstraints(min_length=2, max_length=64)]
    employee_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    phone: Annotated[str, StringConstraints(min_length=5, max_length=32)]
    designation: Annotated[str | None, Field(default=None, max_length=100)] = None
    project_assignments: Annotated[
        list[ProjectAssignmentSpec], Field(default_factory=list, max_length=25)
    ]
    reason_code: CommandReasonCode = "account_provisioning"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]

    @model_validator(mode="after")
    def validate_create_fields(self) -> "CreateBusinessAccountCommand":
        if self.role.casefold() not in BUSINESS_ROLES:
            raise ValueError("Select a supported business role within the assignment ceiling.")
        seen: set[UUID] = set()
        for item in self.project_assignments:
            if item.project_id in seen:
                raise ValueError("Duplicate project assignment in account creation plan.")
            seen.add(item.project_id)
        return self


class SetAccountStateCommand(_StrictModel):
    command_kind: Literal["set_account_state"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    active: StrictBool
    reason_code: CommandReasonCode = "suspected_access"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


class UnlockAccountCommand(_StrictModel):
    command_kind: Literal["unlock_account"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    reason_code: CommandReasonCode = "failed_sign_in"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


class ChangeBusinessRoleCommand(_StrictModel):
    command_kind: Literal["change_business_role"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    new_role: Annotated[str, StringConstraints(min_length=2, max_length=64)]
    reason_code: CommandReasonCode = "role_adjustment"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]

    @model_validator(mode="after")
    def validate_role_ceiling(self) -> "ChangeBusinessRoleCommand":
        if self.new_role.casefold() not in BUSINESS_ROLES:
            raise ValueError("Select a supported business role within the assignment ceiling.")
        return self


class ChangeProjectMembershipCommand(_StrictModel):
    command_kind: Literal["change_project_membership"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    project_id: UUID
    expected_project_revision: Annotated[int, Field(ge=1)]
    action: Literal["assign", "revoke"]
    role_in_project: Annotated[str | None, Field(default=None, max_length=100)] = None
    reason_code: CommandReasonCode = "project_membership"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]

    @model_validator(mode="after")
    def check_revoke_label(self) -> "ChangeProjectMembershipCommand":
        if self.action == "revoke" and self.role_in_project:
            raise ValueError("A project removal command must not supply a role_in_project label.")
        return self


class RequestAccountRecoveryCommand(_StrictModel):
    command_kind: Literal["request_account_recovery"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    reason_code: CommandReasonCode = "verified_user_report"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


class RevokeBusinessSessionCommand(_StrictModel):
    command_kind: Literal["revoke_business_session"]
    target_user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]
    scope: Literal["selected", "all"]
    session_id: UUID | None = None
    reason_code: CommandReasonCode = "suspected_access"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]

    @model_validator(mode="after")
    def check_session_scope(self) -> "RevokeBusinessSessionCommand":
        if self.scope == "selected" and self.session_id is None:
            raise ValueError("Select a session_id when revoking a single session.")
        if self.scope == "all" and self.session_id is not None:
            raise ValueError("Omit session_id when revoking all business sessions.")
        return self


class UpdateSafeSettingCommand(_StrictModel):
    command_kind: Literal["update_safe_setting"]
    setting_key: Annotated[str, StringConstraints(min_length=2, max_length=64)]
    expected_revision: Annotated[int, Field(ge=0)]
    value: StrictInt | Annotated[str, StringConstraints(max_length=240)]
    reason_code: CommandReasonCode = "operational_configuration"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


class RetrySafeJobCommand(_StrictModel):
    command_kind: Literal["retry_safe_job"]
    job_source: Literal["task_outbox", "support_recovery_delivery"]
    job_id: UUID
    reason_code: CommandReasonCode = "operational_recovery"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]


class BulkAccountTargetSpec(_StrictModel):
    user_id: UUID
    expected_user_revision: Annotated[int, Field(ge=0)]


class BulkAccountLifecycleCommand(_StrictModel):
    command_kind: Literal["bulk_account_lifecycle"]
    operation: Literal["disable", "reactivate", "unlock", "revoke_sessions"]
    targets: Annotated[list[BulkAccountTargetSpec], Field(min_length=1, max_length=25)]
    reason_code: CommandReasonCode = "suspected_access"
    reason: Annotated[str, StringConstraints(min_length=10, max_length=300)]

    @model_validator(mode="after")
    def ensure_unique_targets(self) -> "BulkAccountLifecycleCommand":
        seen: set[UUID] = set()
        for item in self.targets:
            if item.user_id in seen:
                raise ValueError("Duplicate user_id in bulk command target list.")
            seen.add(item.user_id)
        return self


SupportAdminCommandPlanRequest = Annotated[
    CreateBusinessAccountCommand
    | SetAccountStateCommand
    | UnlockAccountCommand
    | ChangeBusinessRoleCommand
    | ChangeProjectMembershipCommand
    | RequestAccountRecoveryCommand
    | RevokeBusinessSessionCommand
    | UpdateSafeSettingCommand
    | RetrySafeJobCommand
    | BulkAccountLifecycleCommand,
    Field(discriminator="command_kind"),
]


class SupportAdminCommandRead(BaseModel):
    command_id: UUID
    command_kind: str
    company_context: str = "garrisons_single_company"
    operator_id: UUID
    session_id: UUID
    case_id: UUID | None = None
    authorization_mode: Literal["single_owner", "paired"]
    target_id: UUID | None = None
    target_revision: int | None = None
    project_id: UUID | None = None
    project_revision: int | None = None
    before: dict[str, Any]
    after: dict[str, Any]
    effects: list[str]
    denied_conditions: list[str]
    requires_action_passkey: bool = True
    policy_version: str
    plan_sha256: str
    reason_code: str
    reason: str
    status: CommandStatus
    result: dict[str, Any] | None = None
    created_at: datetime
    expires_at: datetime
    completed_at: datetime | None = None


class SupportSafeSettingItem(BaseModel):
    key: str
    label: str
    description: str
    value_type: Literal["string", "integer"]
    current_value: str | int
    default_value: str | int
    revision: int
    effect: Literal["immediate", "restart_required"]
    updated_at: datetime | None = None
    updated_by_operator_id: UUID | None = None


class SupportSafeSettingsRead(BaseModel):
    observed_at: datetime
    editable_enabled: bool
    items: list[SupportSafeSettingItem]
    permanently_locked_controls: list[str]


class SupportDataInspectorEntityMeta(BaseModel):
    entity_key: str
    label: str
    description: str
    columns: list[str]
    filterable_statuses: list[str]


class SupportDataInspectorCatalogRead(BaseModel):
    entities: list[SupportDataInspectorEntityMeta]
    excluded_domains_notice: str


class SupportDataInspectorPage(BaseModel):
    entity_key: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int
    limit: int
    offset: int


class SupportCredentialSummary(BaseModel):
    credential_id: UUID
    credential_hash_prefix: str
    sign_count: int
    created_at: datetime
    revoked_at: datetime | None
    status: Literal["active", "revoked"]


class SupportOwnerAuthEventItem(BaseModel):
    id: UUID
    action: str
    request_id: str
    occurred_at: datetime


class SupportOwnerSecurityRead(BaseModel):
    operator_id: UUID
    display_label: str
    status: str
    grant_epoch: int
    custody_mode: Literal["single_owner", "paired", "unknown"]
    bootstrap_activated_at: datetime | None
    session_id: UUID
    session_auth_method: Literal["passkey", "email_otp_only"]
    session_expires_at: datetime
    session_idle_deadline: datetime
    active_passkey_count: int
    minimum_passkeys_required: int
    passkeys: list[SupportCredentialSummary]
    recent_auth_events: list[SupportOwnerAuthEventItem]
    recovery_guidance: list[str]
