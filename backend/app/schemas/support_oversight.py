from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

MetricState = Literal["observed", "suppressed", "unknown", "not_configured", "unavailable"]
SourceStatus = Literal[
    "operational", "degraded", "partial", "unverified", "unknown", "unavailable"
]
FreshnessState = Literal["current", "stale", "unknown"]
OverviewDomain = Literal[
    "company",
    "projects",
    "workforce",
    "inventory",
    "suppliers",
    "documents",
    "finance",
    "approvals",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OversightScope(_StrictModel):
    kind: Literal["approved_company_aggregate", "case_project_scope", "case_scope"]
    case_id: UUID | None = None
    project_id: UUID | None = None


class OversightMetric(_StrictModel):
    key: str
    label: str
    value: int | str | None
    state: MetricState
    source: str
    note: str | None = None


class OversightEnvelope(_StrictModel):
    metric_version: Literal["v1"] = "v1"
    domain: OverviewDomain
    observed_at: AwareDatetime
    scope: OversightScope
    source_status: SourceStatus
    freshness: FreshnessState
    truncated: bool = False
    metrics: list[OversightMetric]


class ProjectStatusBucket(_StrictModel):
    status: str
    count: int


class CaseMaskedProjectSummary(_StrictModel):
    label: str
    status: str
    progress_band: str


class SupportProjectsOverviewRead(OversightEnvelope):
    domain: Literal["projects"] = "projects"
    by_status: list[ProjectStatusBucket] = Field(default_factory=list)
    case_projects: list[CaseMaskedProjectSummary] = Field(default_factory=list)


class WorkforceBucket(_StrictModel):
    status: str
    count: int | None
    state: MetricState


class WorkforceProjectCount(_StrictModel):
    project_label: str
    headcount: int | None
    state: MetricState


class SupportWorkforceOverviewRead(OversightEnvelope):
    domain: Literal["workforce"] = "workforce"
    suppression_threshold: int = 5
    by_status: list[WorkforceBucket] = Field(default_factory=list)
    by_project: list[WorkforceProjectCount] = Field(default_factory=list)


class SupportInventoryOverviewRead(OversightEnvelope):
    domain: Literal["inventory"] = "inventory"


class SupportSuppliersOverviewRead(OversightEnvelope):
    domain: Literal["suppliers"] = "suppliers"


class SupportDocumentsOverviewRead(OversightEnvelope):
    domain: Literal["documents"] = "documents"


class SupportFinanceOverviewRead(OversightEnvelope):
    domain: Literal["finance"] = "finance"
    finance_writes_policy: Literal["blocked"] = "blocked"
    operating_currency: str


class ApprovalWorkflowBucket(_StrictModel):
    request_type: str
    pending: int
    overdue: int
    escalated: int
    rejected: int


class SupportApprovalsOverviewRead(OversightEnvelope):
    domain: Literal["approvals"] = "approvals"
    by_workflow: list[ApprovalWorkflowBucket] = Field(default_factory=list)


class SupportCompanyOverviewRead(OversightEnvelope):
    domain: Literal["company"] = "company"


class SupportPolicyExplainQuery(_StrictModel):
    role_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    permission_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_:]+$")
    case_id: UUID | None = None


class SupportPolicyExplainRead(_StrictModel):
    observed_at: datetime
    role_key: str
    role_label: str
    permission_key: str
    allowed: bool
    reason: str
    is_business_role: bool
    source: Literal["permission_matrix"] = "permission_matrix"


class SupportJobsQuery(_StrictModel):
    hours: int = Field(default=24, ge=1, le=168)
    limit: int = Field(default=25, ge=1, le=50)
    queue: Literal["maintenance", "backup", "email", "reports", "images"] | None = None


class SupportJobScheduleItem(_StrictModel):
    job_name: str
    task_name: str
    queue: str
    state: Literal["scheduled", "disabled_by_policy"]
    schedule_summary: str


class SupportJobEventSummary(_StrictModel):
    event_id: UUID
    task_name: str
    event: Literal["started", "succeeded", "failed", "retried"]
    occurred_at: AwareDatetime


class SupportJobsMonitorRead(_StrictModel):
    metric_version: Literal["v1"] = "v1"
    observed_at: AwareDatetime
    window_hours: int
    broker_status: Literal["operational", "unavailable", "unknown"]
    source_status: SourceStatus
    outbox_pending: int | None
    outbox_failed: int | None
    outbox_oldest_age_seconds: int | None
    recovery_pending: int | None
    recovery_dispatching: int | None
    recovery_unknown: int | None
    schedules: list[SupportJobScheduleItem]
    recent_events: list[SupportJobEventSummary]
    truncated: bool


class SupportBackupReceiptSummary(_StrictModel):
    receipt_id: UUID
    receipt_kind: Literal["scheduled_db_attempt", "authenticated_backup_set", "restore_drill"]
    target_domain: Literal["local_host", "independent_offhost", "isolated_restore"]
    backup_set_id: str | None
    manifest_digest_prefix: str | None
    covers_database: bool
    covers_objects: bool
    outcome: Literal["pass", "fail", "unknown"]
    rpo_minutes: int | None
    rto_minutes: int | None
    captured_at: AwareDatetime
    verified_at: AwareDatetime | None
    signer_key_id: str | None


class SupportBackupsMonitorRead(_StrictModel):
    metric_version: Literal["v1"] = "v1"
    observed_at: AwareDatetime
    source_status: SourceStatus
    overall_recovery_posture: Literal["complete_verified", "partial_db_only", "stale", "unverified"]
    database_backup_status: Literal["current", "stale", "failed", "unverified"]
    authenticated_backup_set_status: Literal["verified", "stale", "failed", "unverified"]
    isolated_restore_status: Literal["verified", "stale", "failed", "unverified"]
    escalation_reference: str
    latest_scheduled_db_task_at: AwareDatetime | None
    receipts: list[SupportBackupReceiptSummary]


class SupportConfigStatusRead(_StrictModel):
    metric_version: Literal["v1"] = "v1"
    observed_at: AwareDatetime
    source_status: SourceStatus
    app_env: str
    source_sha: str
    business_currency: str
    business_timezone: str
    audit_purge_disabled: bool
    mail_configured: bool
    support_portal_enabled: bool
    support_recovery_delivery_enabled: bool
    support_email_otp_configured: bool
    support_otp_recipient_count: int
    hr_encryption_configured: bool
    backup_encryption_configured: bool
    scheduler_jobs_configured: int
    tls_status: Literal["valid", "expiring_soon", "expired", "unknown"]
    tls_not_after: AwareDatetime | None
    change_control_reference: str


class SupportIncidentsQuery(_StrictModel):
    hours: int = Field(default=24, ge=1, le=24)
    case_id: UUID | None = None


class SupportIncidentsSummaryRead(_StrictModel):
    metric_version: Literal["v1"] = "v1"
    observed_at: AwareDatetime
    window_hours: int
    scope: OversightScope
    source_status: SourceStatus
    freshness: FreshnessState
    metrics: list[OversightMetric]
