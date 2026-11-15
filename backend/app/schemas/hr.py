from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# --- Enums / Literals ---

EmploymentStatus = Literal[
    "draft",
    "onboarding",
    "active",
    "on_probation",
    "on_leave",
    "notice_period",
    "suspended",
    "terminated",
    "resigned",
    "archived",
]
EmploymentCategory = Literal[
    "permanent",
    "contract",
    "probation",
    "daily_wage",
    "intern",
    "consultant",
]
AccessRequestType = Literal[
    "provision",
    "role_change",
    "deactivate",
    "reactivate",
    "link_existing",
]
AccessRequestStatus = Literal[
    "draft",
    "submitted",
    "hr_approved",
    "admin_actioned",
    "rejected",
    "cancelled",
]
HrDocumentCategory = Literal[
    "ordinary",
    "confidential",
    "medical",
    "compensation",
    "disciplinary",
]
AttendanceStatus = Literal[
    "present",
    "absent",
    "half_day",
    "on_leave",
    "holiday",
    "remote",
    "site_duty",
]


# --- Departments & Positions ---


class DepartmentCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    parent_department_id: UUID | None = None
    head_employee_id: UUID | None = None
    project_id: UUID | None = None
    description: str | None = None


class DepartmentUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    parent_department_id: UUID | None = None
    head_employee_id: UUID | None = None
    project_id: UUID | None = None
    is_active: bool | None = None
    description: str | None = None


class DepartmentResponse(BaseModel):
    id: UUID
    code: str
    name: str
    parent_department_id: UUID | None
    head_employee_id: UUID | None
    project_id: UUID | None
    is_active: bool
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentListResponse(BaseModel):
    items: list[DepartmentResponse]
    total: int


class PositionCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=160)
    department_id: UUID | None = None
    grade: str | None = Field(default=None, max_length=40)
    employment_category: EmploymentCategory = "permanent"
    headcount_limit: int = Field(default=1, ge=1)
    approved_count: int = Field(default=1, ge=0)
    description: str | None = None


class PositionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=160)
    department_id: UUID | None = None
    grade: str | None = Field(default=None, max_length=40)
    employment_category: EmploymentCategory | None = None
    headcount_limit: int | None = Field(default=None, ge=1)
    approved_count: int | None = Field(default=None, ge=0)
    is_active: bool | None = None
    description: str | None = None


class PositionResponse(BaseModel):
    id: UUID
    code: str
    title: str
    department_id: UUID | None
    grade: str | None
    employment_category: str
    headcount_limit: int
    approved_count: int
    is_active: bool
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PositionListResponse(BaseModel):
    items: list[PositionResponse]
    total: int


class OrgChartNode(BaseModel):
    employee_id: UUID
    employee_code: str
    full_name: str
    employment_status: str
    department_id: UUID | None
    department_name: str | None = None
    position_id: UUID | None
    position_title: str | None = None
    manager_employee_id: UUID | None
    work_location: str | None = None
    primary_assignment: Literal["none", "active", "inactive"] = "none"
    direct_reports: list["OrgChartNode"] = Field(default_factory=list)


class OrgChartResponse(BaseModel):
    roots: list[OrgChartNode]
    total_employees: int


class HrProjectAssignmentCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    action: Literal["assign", "revoke"]
    role_in_project: str | None = Field(default=None, max_length=50)
    reason: str = Field(min_length=1, max_length=500)


class HrProjectAssignmentDecision(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    decision: Literal["approve", "reject"]
    expected_project_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class HrProjectAssignmentResponse(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    project_id: UUID
    project_code: str
    project_name: str
    action: str
    status: str
    role_in_project: str | None
    reason: str
    decision_note: str | None
    decided_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HrProjectAssignmentListResponse(BaseModel):
    items: list[HrProjectAssignmentResponse]
    total: int


# --- Employees & Projections ---


class EmployeeCreateRequest(BaseModel):
    employee_code: str = Field(min_length=1, max_length=40)
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    preferred_name: str | None = Field(default=None, max_length=120)
    full_name: str | None = Field(default=None, max_length=255)
    work_email: EmailStr | None = None
    work_phone: str | None = Field(default=None, max_length=32)
    employment_status: EmploymentStatus = "draft"
    employment_category: EmploymentCategory = "permanent"
    join_date: date | None = None
    confirmation_date: date | None = None
    department_id: UUID | None = None
    position_id: UUID | None = None
    primary_project_id: UUID | None = None
    manager_employee_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=160)
    work_calendar_id: UUID | None = None
    override_headcount: bool = False
    reason: str | None = None


class EmployeeUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    employee_code: str | None = Field(default=None, min_length=1, max_length=40)
    first_name: str | None = Field(default=None, min_length=1, max_length=120)
    last_name: str | None = Field(default=None, min_length=1, max_length=120)
    preferred_name: str | None = Field(default=None, max_length=120)
    full_name: str | None = Field(default=None, max_length=255)
    work_email: EmailStr | None = None
    work_phone: str | None = Field(default=None, max_length=32)
    employment_category: EmploymentCategory | None = None
    join_date: date | None = None
    confirmation_date: date | None = None
    department_id: UUID | None = None
    position_id: UUID | None = None
    primary_project_id: UUID | None = None
    manager_employee_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=160)
    work_calendar_id: UUID | None = None
    override_headcount: bool = False
    reason: str | None = None


class EmployeeStatusTransitionRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    status: EmploymentStatus
    effective_date: date | None = None
    reason: str = Field(min_length=2, max_length=500)


class EmployeeDirectoryResponse(BaseModel):
    id: UUID
    employee_code: str
    full_name: str
    preferred_name: str | None
    work_email: str | None
    work_phone: str | None
    employment_status: str
    employment_category: str
    department_id: UUID | None
    department_name: str | None = None
    position_id: UUID | None
    position_title: str | None = None
    primary_project_id: UUID | None
    manager_employee_id: UUID | None
    work_location: str | None
    join_date: date | None

    model_config = ConfigDict(from_attributes=True)


class EmployeeDirectoryListResponse(BaseModel):
    items: list[EmployeeDirectoryResponse]
    total: int


class EmployeeDetailResponse(EmployeeDirectoryResponse):
    first_name: str
    last_name: str
    user_id: UUID | None
    confirmation_date: date | None
    termination_date: date | None
    work_calendar_id: UUID | None
    line_manager_reviewer_id: UUID | None
    record_revision: int
    created_at: datetime
    updated_at: datetime


class EmployeeManagerReviewRequest(BaseModel):
    enabled: bool
    expected_revision: int = Field(ge=1)


class EmployeePrivateUpdateRequest(BaseModel):
    national_id: str | None = Field(default=None, max_length=64)
    passport_number: str | None = Field(default=None, max_length=64)
    date_of_birth: date | None = None
    gender: str | None = Field(default=None, max_length=30)
    marital_status: str | None = Field(default=None, max_length=30)
    nationality: str | None = Field(default=None, max_length=80)
    personal_email: EmailStr | None = None
    personal_phone: str | None = Field(default=None, max_length=32)
    residential_address: str | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    emergency_contact_relation: str | None = Field(default=None, max_length=80)
    bank_name: str | None = Field(default=None, max_length=120)
    bank_branch: str | None = Field(default=None, max_length=120)
    bank_account_number: str | None = Field(default=None, max_length=64)
    tax_id: str | None = Field(default=None, max_length=64)
    epf_number: str | None = Field(default=None, max_length=64)
    etf_number: str | None = Field(default=None, max_length=64)
    medical_notes: str | None = None


class EmployeeSensitiveResponse(BaseModel):
    employee_id: UUID
    national_id_masked: str | None = None
    passport_masked: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    marital_status: str | None = None
    nationality: str | None = None
    personal_email: str | None = None
    personal_phone: str | None = None
    residential_address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    bank_name: str | None = None
    bank_branch: str | None = None
    bank_account_masked: str | None = None
    tax_id_masked: str | None = None
    epf_number_masked: str | None = None
    etf_number_masked: str | None = None
    national_id_plain: str | None = None
    passport_plain: str | None = None
    bank_account_plain: str | None = None
    tax_id_plain: str | None = None
    epf_number_plain: str | None = None
    etf_number_plain: str | None = None
    medical_notes_plain: str | None = None
    updated_at: datetime | None = None


class EmployeeSelfResponse(BaseModel):
    employee: EmployeeDetailResponse
    personal_email: str | None = None
    personal_phone: str | None = None
    residential_address: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    emergency_contact_relation: str | None = None
    bank_name: str | None = None
    bank_account_masked: str | None = None
    tax_id_masked: str | None = None
    epf_number_masked: str | None = None
    etf_number_masked: str | None = None


class EmployeeSelfUpdateRequest(BaseModel):
    preferred_name: str | None = Field(default=None, max_length=120)
    work_phone: str | None = Field(default=None, max_length=32)
    personal_email: EmailStr | None = None
    personal_phone: str | None = Field(default=None, max_length=32)
    residential_address: str | None = None
    emergency_contact_name: str | None = Field(default=None, max_length=160)
    emergency_contact_phone: str | None = Field(default=None, max_length=32)
    emergency_contact_relation: str | None = Field(default=None, max_length=80)


class EmploymentHistoryResponse(BaseModel):
    id: UUID
    employee_id: UUID
    change_type: str
    effective_date: date
    previous_snapshot: dict[str, Any] | None
    new_snapshot: dict[str, Any]
    reason: str | None
    actor_user_id: UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmploymentHistoryListResponse(BaseModel):
    items: list[EmploymentHistoryResponse]
    total: int


# --- Portal Account Link & Access Requests ---


class EmployeeLinkAccountRequest(BaseModel):
    user_id: UUID


class AccessRequestCreateRequest(BaseModel):
    employee_id: UUID
    request_type: AccessRequestType
    requested_role: str | None = Field(default=None, max_length=64)
    requested_email: EmailStr | None = None
    portal_access_required: bool = True
    business_title_source: str | None = Field(default=None, max_length=160)
    justification: str | None = None
    submit_immediately: bool = False


class AccessRequestDecisionRequest(BaseModel):
    action: Literal["submit", "hr_approve", "admin_action", "reject", "cancel"]
    notes: str | None = None
    temporary_password: str | None = Field(default=None, min_length=8, max_length=256)
    link_existing_user_id: UUID | None = None


class AccessRequestResponse(BaseModel):
    id: UUID
    employee_id: UUID
    request_type: str
    requested_role: str | None
    requested_email: str | None
    portal_access_required: bool
    business_title_source: str | None
    status: str
    justification: str | None
    hr_decision_notes: str | None
    admin_decision_notes: str | None
    requested_by_id: UUID | None
    hr_approved_by_id: UUID | None
    hr_approved_at: datetime | None
    admin_actioned_by_id: UUID | None
    admin_actioned_at: datetime | None
    linked_user_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AccessRequestListResponse(BaseModel):
    items: list[AccessRequestResponse]
    total: int


# --- Workbook 7-Column Import Preview & Apply (HR-006) ---


class WorkbookRowInput(BaseModel):
    user_name: str = ""
    email_source: str = ""
    portal_access_required: str = ""
    role_to_assign: str = ""
    role_description_auto: str = ""
    privileges_auto: str = ""
    access_scope_auto: str = ""


class WorkbookRowPreview(BaseModel):
    row_number: int
    user_name: str
    email_source: str
    portal_access_required_raw: str
    portal_access_required: bool
    role_source: str
    role_description_auto: str
    privileges_auto: str
    access_scope_auto: str
    status: Literal[
        "ready_for_employee_and_access_request",
        "ready_employee_only_no_portal_access",
        "blocked_missing_email",
        "blocked_unmapped_role",
        "already_linked",
    ]
    role_mapping_status: Literal["valid_portal_role", "unmapped_business_title", "not_required"]
    mapped_role: str | None = None
    issues: list[str] = Field(default_factory=list)
    can_import_employee: bool
    can_provision_user: bool
    matched_employee_id: UUID | None = None
    matched_user_id: UUID | None = None


class WorkbookPreviewResponse(BaseModel):
    total_rows: int
    ready_employee_rows: int
    ready_access_request_rows: int
    blocked_missing_email_rows: int
    unmapped_role_rows: int
    already_linked_rows: int
    rows: list[WorkbookRowPreview]


class WorkbookApplyRequest(BaseModel):
    rows: list[WorkbookRowInput]
    explicit_role_overrides: dict[str, str] = Field(default_factory=dict)
    allow_missing_email_draft: bool = True
    create_access_requests: bool = True


class WorkbookApplyItem(BaseModel):
    row_number: int
    user_name: str
    outcome: Literal["created_employee", "updated_employee", "skipped", "blocked"]
    employee_id: UUID | None = None
    access_request_id: UUID | None = None
    message: str


class WorkbookApplyResponse(BaseModel):
    employees_created: int
    employees_updated: int
    access_requests_created: int
    skipped_rows: int
    blocked_rows: int
    items: list[WorkbookApplyItem]


# --- Recruitment & Onboarding ---


class RequisitionCreateRequest(BaseModel):
    requisition_code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=180)
    department_id: UUID | None = None
    position_id: UUID | None = None
    project_id: UUID | None = None
    employment_category: EmploymentCategory = "permanent"
    headcount_requested: int = Field(default=1, ge=1)
    justification: str | None = None
    budget_notes: str | None = None
    target_join_date: date | None = None


class RequisitionDecisionRequest(BaseModel):
    status: Literal[
        "submitted", "approved", "rejected", "open", "on_hold", "filled", "closed", "cancelled"
    ]
    notes: str | None = None


class RequisitionResponse(BaseModel):
    id: UUID
    requisition_code: str
    title: str
    department_id: UUID | None
    position_id: UUID | None
    project_id: UUID | None
    employment_category: str
    headcount_requested: int
    status: str
    justification: str | None
    budget_notes: str | None
    requested_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    rejection_reason: str | None = None
    target_join_date: date | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RequisitionListResponse(BaseModel):
    items: list[RequisitionResponse]
    total: int


class CandidateCreateRequest(BaseModel):
    candidate_code: str = Field(min_length=1, max_length=40)
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    source: str | None = Field(default=None, max_length=80)
    current_organization: str | None = Field(default=None, max_length=160)
    years_experience: Decimal | None = None
    notes: str | None = None


class CandidateResponse(BaseModel):
    id: UUID
    candidate_code: str
    full_name: str
    email: str | None
    phone: str | None
    source: str | None
    current_organization: str | None
    years_experience: Decimal | None
    resume_document_id: UUID | None
    notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateListResponse(BaseModel):
    items: list[CandidateResponse]
    total: int


class ApplicationCreateRequest(BaseModel):
    requisition_id: UUID
    candidate_id: UUID
    screening_notes: str | None = None


class ApplicationStageUpdateRequest(BaseModel):
    stage: Literal[
        "applied",
        "screening",
        "interview",
        "evaluation",
        "offer",
        "hired",
        "rejected",
        "withdrawn",
    ]
    overall_score: Decimal | None = None
    screening_notes: str | None = None
    rejection_reason: str | None = None


class ApplicationResponse(BaseModel):
    id: UUID
    requisition_id: UUID
    candidate_id: UUID
    stage: str
    overall_score: Decimal | None
    screening_notes: str | None
    rejection_reason: str | None
    assigned_recruiter_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationListResponse(BaseModel):
    items: list[ApplicationResponse]
    total: int


class InterviewCreateRequest(BaseModel):
    application_id: UUID
    round_number: int = Field(default=1, ge=1)
    interview_type: str = Field(default="technical", max_length=40)
    scheduled_at: datetime | None = None
    interviewer_user_id: UUID | None = None
    interviewer_name: str | None = Field(default=None, max_length=160)


class InterviewUpdateRequest(BaseModel):
    recommendation: Literal["pending", "strong_hire", "hire", "hold", "no_hire"] | None = None
    score: Decimal | None = None
    feedback_notes: str | None = None
    status: Literal["scheduled", "completed", "cancelled"] | None = None


class InterviewResponse(BaseModel):
    id: UUID
    application_id: UUID
    round_number: int
    interview_type: str
    scheduled_at: datetime | None
    interviewer_user_id: UUID | None
    interviewer_name: str | None
    recommendation: str
    score: Decimal | None
    feedback_notes: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InterviewListResponse(BaseModel):
    items: list[InterviewResponse]
    total: int


class OfferCreateRequest(BaseModel):
    offer_code: str = Field(min_length=1, max_length=40)
    application_id: UUID
    proposed_title: str = Field(min_length=2, max_length=160)
    proposed_department_id: UUID | None = None
    proposed_position_id: UUID | None = None
    proposed_join_date: date | None = None
    proposed_salary: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=10)
    valid_until: date | None = None
    supersedes_offer_id: UUID | None = None
    notes: str | None = None


class OfferReissueRequest(BaseModel):
    offer_code: str = Field(min_length=1, max_length=40)
    proposed_title: str = Field(min_length=2, max_length=160)
    proposed_department_id: UUID | None = None
    proposed_position_id: UUID | None = None
    proposed_join_date: date | None = None
    proposed_salary: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=10)
    valid_until: date | None = None
    notes: str | None = None


class OfferDecisionRequest(BaseModel):
    status: Literal[
        "pending_approval",
        "approved",
        "issued",
        "accepted",
        "declined",
        "expired",
        "withdrawn",
    ]
    valid_until: date | None = None
    expected_version_number: int | None = Field(default=None, ge=1)
    notes: str | None = None


class OfferConvertRequest(BaseModel):
    employee_code: str = Field(min_length=1, max_length=40)
    work_email: EmailStr | None = None
    work_phone: str | None = None
    join_date: date | None = None
    probation_days: int = Field(default=0, ge=0, le=365)


class OfferResponse(BaseModel):
    id: UUID
    offer_code: str
    application_id: UUID
    proposed_title: str
    proposed_department_id: UUID | None
    proposed_position_id: UUID | None
    proposed_join_date: date | None
    proposed_salary_masked: str | None
    currency: str
    status: str
    valid_until: date | None = None
    version_number: int = 1
    supersedes_offer_id: UUID | None = None
    superseded_by_id: UUID | None = None
    superseded_at: datetime | None = None
    approved_by_id: UUID | None
    approved_at: datetime | None
    issued_at: datetime | None
    responded_at: datetime | None
    converted_employee_id: UUID | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OfferListResponse(BaseModel):
    items: list[OfferResponse]
    total: int


class OnboardingTaskResponse(BaseModel):
    id: UUID
    onboarding_case_id: UUID
    code: str
    title: str
    assignee_role: str
    assigned_user_id: UUID | None
    is_mandatory: bool
    status: str
    due_date: date | None
    completed_by_id: UUID | None
    completed_at: datetime | None
    evidence_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OnboardingTaskUpdateRequest(BaseModel):
    status: Literal["pending", "in_progress", "completed", "waived"]
    evidence_notes: str | None = None


class OnboardingCaseCreateRequest(BaseModel):
    employee_id: UUID
    start_date: date
    probation_end_date: date | None = None
    owner_user_id: UUID | None = None


class OnboardingCaseResponse(BaseModel):
    id: UUID
    employee_id: UUID
    offer_id: UUID | None
    status: str
    start_date: date
    probation_end_date: date | None
    employee_name: str | None = None
    employee_status: str | None = None
    employee_revision: int | None = None
    employee_category: str | None = None
    owner_user_id: UUID | None
    completion_notes: str | None
    completed_at: datetime | None
    tasks: list[OnboardingTaskResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OnboardingCaseListResponse(BaseModel):
    items: list[OnboardingCaseResponse]
    total: int


class ProbationReviewRequest(BaseModel):
    outcome: Literal["confirm", "extend"]
    expected_employee_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=500)
    new_end_date: date | None = None
    confirmed_category: (
        Literal["permanent", "contract", "daily_wage", "intern", "consultant"] | None
    ) = None


# --- HR Document Vault & Compliance ---


class HrDocumentVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    status: str
    file_name: str
    mime_type: str
    file_size: int
    sha256_checksum: str
    uploaded_by_id: UUID | None
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HrDocumentResponse(BaseModel):
    id: UUID
    employee_id: UUID | None
    candidate_id: UUID | None
    title: str
    document_type: str
    category: str
    current_version: int
    issue_date: date | None
    expiry_date: date | None
    issuing_authority: str | None
    reference_number: str | None
    status: str
    alert_days_before: int
    is_employee_visible: bool
    created_by_id: UUID | None
    versions: list[HrDocumentVersionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HrDocumentListResponse(BaseModel):
    items: list[HrDocumentResponse]
    total: int


class HrDocumentDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    notes: str | None = Field(default=None, max_length=500)


class HrDocumentDownloadResponse(BaseModel):
    document_id: UUID
    version_number: int
    file_name: str
    download_url: str
    expires_in_seconds: int


class ComplianceItemResponse(BaseModel):
    source_type: Literal["document", "certification"]
    record_id: UUID
    employee_id: UUID | None
    title: str
    expiry_date: date
    days_remaining: int
    status: str


class ExpiringComplianceResponse(BaseModel):
    within_days: int
    items: list[ComplianceItemResponse]
    total: int


# --- Calendars, Shifts, Attendance, Corrections, Timesheets, Overtime ---


class WorkCalendarCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    work_days_json: list[Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]] = Field(
        min_length=1, max_length=7
    )
    standard_start_time: time
    standard_end_time: time
    daily_hours: Decimal = Field(gt=0, le=24, decimal_places=2)
    is_default: bool = False
    project_id: UUID | None = None
    effective_from: date
    effective_to: date
    timezone: str = Field(min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Enter an IANA timezone such as Asia/Colombo or UTC.") from exc
        return value


class WorkCalendarDecisionRequest(BaseModel):
    action: Literal["submit", "approve", "return_to_draft", "publish"]
    expected_revision: int = Field(ge=1)
    reason: str | None = Field(default=None, min_length=2, max_length=500)


class WorkCalendarUpdateRequest(WorkCalendarCreateRequest):
    expected_revision: int = Field(ge=1)


class WorkCalendarResponse(BaseModel):
    id: UUID
    code: str
    name: str
    work_days_json: list[str]
    standard_start_time: time
    standard_end_time: time
    daily_hours: Decimal
    is_default: bool
    project_id: UUID | None
    effective_from: date | None
    effective_to: date | None
    timezone: str | None
    status: Literal["draft", "submitted", "approved", "published"]
    revision: int
    created_by_id: UUID | None
    submitted_by_id: UUID | None
    approved_by_id: UUID | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WorkCalendarListResponse(BaseModel):
    items: list[WorkCalendarResponse]
    total: int


class HolidayCreateRequest(BaseModel):
    calendar_id: UUID
    holiday_date: date
    name: str = Field(min_length=2, max_length=160)
    holiday_type: Literal["mercantile", "public", "poya", "company"] = "public"
    is_paid: bool = True


class HolidayResponse(BaseModel):
    id: UUID
    calendar_id: UUID
    holiday_date: date
    name: str
    holiday_type: str
    is_paid: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HolidayListResponse(BaseModel):
    items: list[HolidayResponse]
    total: int


class ShiftAssignmentCreateRequest(BaseModel):
    employee_id: UUID
    calendar_id: UUID
    project_id: UUID | None = None
    shift_name: str = Field(min_length=1, max_length=80)
    effective_from: date
    effective_to: date | None = None
    start_time: time
    end_time: time


class ShiftAssignmentResponse(BaseModel):
    id: UUID
    employee_id: UUID
    calendar_id: UUID
    project_id: UUID | None
    shift_name: str
    effective_from: date
    effective_to: date | None
    start_time: time
    end_time: time
    assigned_by_id: UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ShiftAssignmentListResponse(BaseModel):
    items: list[ShiftAssignmentResponse]
    total: int


class WorkScheduleResponse(BaseModel):
    work_date: date
    calendar: WorkCalendarResponse | None = None
    shift: ShiftAssignmentResponse | None = None
    holiday: HolidayResponse | None = None
    is_workday: bool | None = None


class AttendanceEntryCreateRequest(BaseModel):
    employee_id: UUID
    work_date: date
    project_id: UUID | None = None
    attendance_status: AttendanceStatus
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    worked_hours: Decimal = Field(ge=0, le=24, decimal_places=2)
    source: Literal["manual", "self_service", "import", "correction"] = "manual"
    notes: str | None = None


class ManagerRecommendationResponse(BaseModel):
    record_revision: int
    requires_manager_recommendation: bool
    manager_recommendation: Literal["support", "flag"] | None
    manager_recommended_at: datetime | None


class AttendanceEntryResponse(ManagerRecommendationResponse):
    id: UUID
    employee_id: UUID
    work_date: date
    calendar_id: UUID | None
    shift_assignment_id: UUID | None
    scheduled_workday: bool | None
    project_id: UUID | None
    attendance_status: str
    status: Literal["submitted", "approved", "returned", "historical"]
    review_note: str | None
    check_in_at: datetime | None
    check_out_at: datetime | None
    worked_hours: Decimal
    source: str
    notes: str | None
    recorded_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttendanceEntryListResponse(BaseModel):
    items: list[AttendanceEntryResponse]
    total: int


class AttendanceReviewRequest(BaseModel):
    decision: Literal["approved", "returned"]
    expected_revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=500)


class AttendanceImportRowResponse(BaseModel):
    row: int
    employee_code: str | None = None
    work_date: date | None = None
    attendance_status: str | None = None
    worked_hours: Decimal | None = None
    error: str | None = None


class AttendanceImportPreviewResponse(BaseModel):
    items: list[AttendanceImportRowResponse]
    digest: str | None = None


class AttendanceCorrectionSelfRequest(BaseModel):
    work_date: date
    attendance_entry_id: UUID | None = None
    requested_status: AttendanceStatus
    requested_check_in_at: datetime | None = None
    requested_check_out_at: datetime | None = None
    requested_worked_hours: Decimal = Field(ge=0, le=24, decimal_places=2)
    reason: str = Field(min_length=2, max_length=500)


class AttendanceCorrectionCreateRequest(AttendanceCorrectionSelfRequest):
    employee_id: UUID


class AttendanceCorrectionDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "cancelled"]
    notes: str | None = None


class AttendanceCorrectionResponse(BaseModel):
    id: UUID
    attendance_entry_id: UUID | None
    employee_id: UUID
    work_date: date
    requested_status: str
    requested_check_in_at: datetime | None
    requested_check_out_at: datetime | None
    requested_worked_hours: Decimal
    reason: str
    status: str
    requested_by_id: UUID | None
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AttendanceCorrectionListResponse(BaseModel):
    items: list[AttendanceCorrectionResponse]
    total: int


class TimesheetHoursRequest(BaseModel):
    regular_hours: Decimal = Field(ge=0, max_digits=6, decimal_places=2)
    overtime_hours: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=6, decimal_places=2)
    notes: str | None = None
    model_config = ConfigDict(extra="forbid")


class TimesheetSelfCreateRequest(TimesheetHoursRequest):
    period_start: date
    period_end: date


class TimesheetSelfResubmitRequest(TimesheetHoursRequest):
    expected_revision: int = Field(ge=1)


class TimesheetCreateRequest(TimesheetSelfCreateRequest):
    employee_id: UUID
    project_id: UUID | None = None
    submit: bool = False


class TimesheetDecisionRequest(BaseModel):
    decision: Literal["submitted", "approved", "rejected", "locked"]
    notes: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


ManagerReviewKind = Literal["attendance", "leave", "timesheet", "overtime"]


class HrWorkflowOptionsResponse(BaseModel):
    can_recommend: bool
    self_time_submission_enabled: bool


class ManagerReviewDecisionRequest(BaseModel):
    recommendation: Literal["support", "flag"]
    expected_revision: int = Field(ge=1)


class ManagerReviewItemResponse(BaseModel):
    kind: ManagerReviewKind
    id: UUID
    employee_name: str
    start_date: date
    end_date: date
    requested_amount: Decimal
    record_revision: int


class ManagerReviewListResponse(BaseModel):
    items: list[ManagerReviewItemResponse]
    has_more: bool


class TimesheetResponse(ManagerRecommendationResponse):
    id: UUID
    employee_id: UUID
    project_id: UUID | None
    period_start: date
    period_end: date
    regular_hours: Decimal
    overtime_hours: Decimal
    status: str
    submitted_at: datetime | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    rejection_reason: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TimesheetListResponse(BaseModel):
    items: list[TimesheetResponse]
    total: int


class OvertimeSelfCreateRequest(BaseModel):
    work_date: date
    requested_hours: Decimal = Field(gt=0, le=24, max_digits=5, decimal_places=2)
    reason: str = Field(min_length=2, max_length=500)
    model_config = ConfigDict(extra="forbid")


class OvertimeRequestCreateRequest(OvertimeSelfCreateRequest):
    employee_id: UUID
    project_id: UUID | None = None


class OvertimeDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "cancelled"]
    approved_hours: Decimal | None = Field(default=None, ge=0, le=24)
    notes: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class OvertimeRequestResponse(ManagerRecommendationResponse):
    id: UUID
    employee_id: UUID
    project_id: UUID | None
    work_date: date
    requested_hours: Decimal
    approved_hours: Decimal | None
    reason: str
    status: str
    requested_by_id: UUID | None
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OvertimeRequestListResponse(BaseModel):
    items: list[OvertimeRequestResponse]
    total: int


# --- Leave Management ---


class LeaveTypeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=120)
    is_paid: bool = True
    requires_attachment: bool = False
    allow_half_day: bool = True
    description: str | None = None


class LeaveTypeResponse(BaseModel):
    id: UUID
    code: str
    name: str
    is_paid: bool
    requires_attachment: bool
    allow_half_day: bool
    is_active: bool
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeaveTypeListResponse(BaseModel):
    items: list[LeaveTypeResponse]
    total: int


class LeavePolicyCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    leave_type_id: UUID
    employment_category: EmploymentCategory | None = None
    annual_entitlement_days: Decimal = Field(ge=0)
    accrual_frequency: Literal["annual", "monthly", "manual"] = "annual"
    max_carry_forward_days: Decimal = Field(default=Decimal("0.00"), ge=0)
    allow_negative_balance: bool = False
    approve_immediately: bool = False


class LeavePolicyResponse(BaseModel):
    id: UUID
    code: str
    name: str
    leave_type_id: UUID
    employment_category: str | None
    annual_entitlement_days: Decimal
    accrual_frequency: str
    max_carry_forward_days: Decimal
    allow_negative_balance: bool
    is_active: bool
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeavePolicyListResponse(BaseModel):
    items: list[LeavePolicyResponse]
    total: int


class LeaveLedgerAdjustRequest(BaseModel):
    employee_id: UUID
    leave_type_id: UUID
    entry_type: Literal["opening_balance", "accrual", "adjustment", "carry_forward", "encashment"]
    days_delta: Decimal = Field(max_digits=6, decimal_places=2)
    leave_year: int = Field(ge=2020, le=2100)
    reason: str = Field(min_length=2, max_length=500)


class LeaveLedgerEntryResponse(BaseModel):
    id: UUID
    employee_id: UUID
    leave_type_id: UUID
    entry_type: str
    days_delta: Decimal
    leave_year: int
    reference_request_id: UUID | None
    reason: str
    actor_user_id: UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeaveBalanceItem(BaseModel):
    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    leave_year: int
    balance_days: Decimal


class LeaveBalanceListResponse(BaseModel):
    employee_id: UUID
    items: list[LeaveBalanceItem]


class LeaveRequestCreateRequest(BaseModel):
    employee_id: UUID | None = None
    leave_type_id: UUID
    start_date: date
    end_date: date
    days_requested: Decimal = Field(gt=0, max_digits=6, decimal_places=2)
    is_half_day: bool = False
    half_day_period: Literal["morning", "afternoon"] | None = None
    reason: str | None = None
    attachment_document_id: UUID | None = None
    submit_immediately: bool = True


class LeaveRequestDecisionRequest(BaseModel):
    decision: Literal["submitted", "approved", "rejected", "cancelled"]
    notes: str | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class LeaveRequestResponse(ManagerRecommendationResponse):
    id: UUID
    employee_id: UUID
    leave_type_id: UUID
    start_date: date
    end_date: date
    days_requested: Decimal
    is_half_day: bool
    half_day_period: str | None
    reason: str | None
    attachment_document_id: UUID | None
    status: str
    requested_by_id: UUID | None
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LeaveRequestListResponse(BaseModel):
    items: list[LeaveRequestResponse]
    total: int


# --- Policies, Letter Templates, HR Service Requests ---


class PolicyDocumentCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    version: str = Field(default="1.0", max_length=20)
    effective_date: date
    content_summary: str = Field(min_length=5)
    document_id: UUID | None = None
    requires_acknowledgement: bool = True


class PolicyDocumentResponse(BaseModel):
    id: UUID
    code: str
    title: str
    version: str
    effective_date: date
    content_summary: str
    document_id: UUID | None
    requires_acknowledgement: bool
    is_active: bool
    published_by_id: UUID | None
    published_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicyDocumentListResponse(BaseModel):
    items: list[PolicyDocumentResponse]
    total: int


class PolicyAcknowledgeRequest(BaseModel):
    notes: str | None = None


class PolicyAcknowledgementResponse(BaseModel):
    id: UUID
    policy_id: UUID
    employee_id: UUID
    acknowledged_at: datetime
    acknowledged_by_user_id: UUID | None
    notes: str | None

    model_config = ConfigDict(from_attributes=True)


class LetterTemplateCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    letter_type: Literal[
        "employment_confirmation",
        "salary_confirmation",
        "experience_letter",
        "warning_letter",
        "transfer_letter",
        "custom",
    ]
    subject_template: str = Field(min_length=2, max_length=255)
    body_template: str = Field(min_length=5)
    requires_hr_manager: bool = False


class LetterTemplateResponse(BaseModel):
    id: UUID
    code: str
    name: str
    letter_type: str
    subject_template: str
    body_template: str
    requires_hr_manager: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LetterTemplateListResponse(BaseModel):
    items: list[LetterTemplateResponse]
    total: int


class LetterGenerateRequest(BaseModel):
    template_id: UUID
    employee_id: UUID
    extra_vars: dict[str, str] = Field(default_factory=dict)


class LetterRenderResponse(BaseModel):
    template_id: UUID
    employee_id: UUID
    subject: str
    body: str


class HrServiceRequestCreateRequest(BaseModel):
    employee_id: UUID | None = None
    request_type: Literal[
        "employment_letter",
        "address_change",
        "emergency_contact_change",
        "general_inquiry",
        "policy_question",
        "other",
    ]
    subject: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class HrServiceRequestResolveRequest(BaseModel):
    status: Literal["in_review", "approved", "completed", "rejected", "cancelled"]
    resolution_notes: str | None = None
    generated_document_id: UUID | None = None
    expected_updated_at: AwareDatetime | None = None


class HrServiceRequestReopenRequest(BaseModel):
    expected_updated_at: AwareDatetime


class HrServiceRequestResponse(BaseModel):
    id: UUID
    request_code: str
    employee_id: UUID
    request_type: str
    subject: str
    description: str | None
    payload_json: dict[str, Any] | None
    status: str
    assigned_to_id: UUID | None
    resolution_notes: str | None
    resolved_by_id: UUID | None
    resolved_at: datetime | None
    generated_document_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class HrServiceRequestListResponse(BaseModel):
    items: list[HrServiceRequestResponse]
    total: int


# --- Offboarding & Clearance ---


class OffboardingInitiateRequest(BaseModel):
    employee_id: UUID
    separation_type: Literal["resignation", "termination", "contract_end", "retirement", "mutual"]
    notice_date: date | None = None
    last_working_date: date
    reason: str | None = None


class OffboardingStepUpdateRequest(BaseModel):
    status: Literal["pending", "cleared", "flagged", "waived"]
    notes: str | None = None


class OffboardingCompleteRequest(BaseModel):
    exit_interview_notes: str | None = None
    rehire_eligible: bool | None = None


class ClearanceStepResponse(BaseModel):
    id: UUID
    offboarding_case_id: UUID
    department_area: str
    title: str
    assigned_user_id: UUID | None
    status: str
    notes: str | None
    cleared_by_id: UUID | None
    cleared_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OffboardingCaseResponse(BaseModel):
    id: UUID
    employee_id: UUID
    separation_type: str
    notice_date: date | None
    last_working_date: date
    reason: str | None
    status: str
    exit_interview_notes: str | None
    rehire_eligible: bool | None
    access_revoked_at: datetime | None
    initiated_by_id: UUID | None
    completed_by_id: UUID | None
    completed_at: datetime | None
    steps: list[ClearanceStepResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OffboardingCaseListResponse(BaseModel):
    items: list[OffboardingCaseResponse]
    total: int


# --- P2 Policy-Gated Modules & Reports ---


class GoalCreateRequest(BaseModel):
    employee_id: UUID
    cycle_name: str = Field(min_length=2, max_length=80)
    title: str = Field(min_length=2, max_length=200)
    description: str | None = None
    target_date: date | None = None
    weight_percent: Decimal = Field(default=Decimal("100.00"), gt=0, le=100)


class GoalUpdateRequest(BaseModel):
    progress_percent: Decimal | None = Field(default=None, ge=0, le=100)
    status: Literal["active", "completed", "deferred", "cancelled"] | None = None


class GoalResponse(BaseModel):
    id: UUID
    employee_id: UUID
    cycle_name: str
    title: str
    description: str | None
    target_date: date | None
    weight_percent: Decimal
    progress_percent: Decimal
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GoalListResponse(BaseModel):
    items: list[GoalResponse]
    total: int


class ReviewCycleCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    start_date: date
    end_date: date


class ReviewCycleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    start_date: date
    end_date: date
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewCycleListResponse(BaseModel):
    items: list[ReviewCycleResponse]
    total: int


class ReviewCreateRequest(BaseModel):
    cycle_id: UUID
    employee_id: UUID
    reviewer_employee_id: UUID | None = None
    self_rating: Decimal | None = None
    manager_rating: Decimal | None = None
    final_rating: Decimal | None = None
    summary_notes: str | None = None
    status: Literal["draft", "self_submitted", "manager_reviewed", "calibrated", "closed"] = "draft"


class ReviewResponse(BaseModel):
    id: UUID
    cycle_id: UUID
    employee_id: UUID
    reviewer_employee_id: UUID | None
    self_rating: Decimal | None
    manager_rating: Decimal | None
    final_rating: Decimal | None
    summary_notes: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    total: int


class TrainingCourseCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    category: str = Field(default="safety", max_length=60)
    provider: str | None = Field(default=None, max_length=160)
    duration_hours: Decimal | None = None
    is_mandatory: bool = False


class TrainingCourseResponse(BaseModel):
    id: UUID
    code: str
    title: str
    category: str
    provider: str | None
    duration_hours: Decimal | None
    is_mandatory: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TrainingCourseListResponse(BaseModel):
    items: list[TrainingCourseResponse]
    total: int


class TrainingEnrollmentCreateRequest(BaseModel):
    course_id: UUID
    employee_id: UUID
    scheduled_date: date | None = None


class TrainingEnrollmentUpdateRequest(BaseModel):
    status: Literal["enrolled", "in_progress", "completed", "no_show", "cancelled"]
    completed_date: date | None = None
    score: Decimal | None = None


class TrainingEnrollmentResponse(BaseModel):
    id: UUID
    course_id: UUID
    employee_id: UUID
    status: str
    scheduled_date: date | None
    completed_date: date | None
    score: Decimal | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TrainingEnrollmentListResponse(BaseModel):
    items: list[TrainingEnrollmentResponse]
    total: int


class CertificationCreateRequest(BaseModel):
    employee_id: UUID
    name: str = Field(min_length=2, max_length=180)
    issuing_body: str | None = Field(default=None, max_length=160)
    certificate_number: str | None = Field(default=None, max_length=80)
    issued_date: date | None = None
    expiry_date: date | None = None
    document_id: UUID | None = None


class CertificationResponse(BaseModel):
    id: UUID
    employee_id: UUID
    name: str
    issuing_body: str | None
    certificate_number: str | None
    issued_date: date | None
    expiry_date: date | None
    document_id: UUID | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CertificationListResponse(BaseModel):
    items: list[CertificationResponse]
    total: int


class BenefitTypeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=40)
    requires_policy_approval: bool = True


class BenefitTypeResponse(BaseModel):
    id: UUID
    code: str
    name: str
    category: str
    requires_policy_approval: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BenefitTypeListResponse(BaseModel):
    items: list[BenefitTypeResponse]
    total: int


class EmployeeBenefitCreateRequest(BaseModel):
    employee_id: UUID
    benefit_type_id: UUID
    effective_from: date
    effective_to: date | None = None
    coverage_notes: str | None = None


class EmployeeBenefitResponse(BaseModel):
    id: UUID
    employee_id: UUID
    benefit_type_id: UUID
    effective_from: date
    effective_to: date | None
    coverage_notes: str | None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmployeeBenefitListResponse(BaseModel):
    items: list[EmployeeBenefitResponse]
    total: int


class ReimbursementCreateRequest(BaseModel):
    employee_id: UUID | None = None
    claim_type: str = Field(min_length=2, max_length=40)
    claim_date: date
    amount: Decimal = Field(gt=0)
    currency: str = Field(default="LKR", max_length=10)
    description: str = Field(min_length=2)
    receipt_document_id: UUID | None = None


class ReimbursementDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "paid", "cancelled"]
    notes: str | None = None


class ReimbursementResponse(BaseModel):
    id: UUID
    claim_code: str
    employee_id: UUID
    claim_type: str
    claim_date: date
    amount: Decimal
    currency: str
    description: str
    receipt_document_id: UUID | None
    status: str
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReimbursementListResponse(BaseModel):
    items: list[ReimbursementResponse]
    total: int


class CompensationTermCreateRequest(BaseModel):
    employee_id: UUID
    effective_from: date
    pay_frequency: Literal["monthly", "biweekly", "weekly", "daily"] = "monthly"
    currency: str = Field(default="LKR", max_length=10)
    base_salary: str = Field(min_length=1, max_length=40)
    allowances_json: dict[str, Any] | None = None


class CompensationTermResponse(BaseModel):
    id: UUID
    employee_id: UUID
    effective_from: date
    pay_frequency: str
    currency: str
    base_salary_masked: str
    base_salary_plain: str | None = None
    is_current: bool
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime


class CompensationTermListResponse(BaseModel):
    items: list[CompensationTermResponse]
    total: int


class PayrollPolicyCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    rules_json: dict[str, Any] = Field(default_factory=dict)


class PayrollPolicyResponse(BaseModel):
    id: UUID
    code: str
    name: str
    rules_json: dict[str, Any]
    is_approved: bool
    approved_by_id: UUID | None
    second_approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollPolicyListResponse(BaseModel):
    items: list[PayrollPolicyResponse]
    total: int


class PayrollPeriodCreateRequest(BaseModel):
    period_code: str = Field(min_length=1, max_length=40)
    period_start: date
    period_end: date
    pay_date: date


class PayrollPeriodResponse(BaseModel):
    id: UUID
    period_code: str
    period_start: date
    period_end: date
    pay_date: date
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollPeriodListResponse(BaseModel):
    items: list[PayrollPeriodResponse]
    total: int


class PayrollRunCreateRequest(BaseModel):
    payroll_period_id: UUID
    policy_id: UUID | None = None
    notes: str | None = None


class PayrollRunResponse(BaseModel):
    id: UUID
    payroll_period_id: UUID
    policy_id: UUID | None
    status: str
    prepared_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollRunListResponse(BaseModel):
    items: list[PayrollRunResponse]
    total: int


class HrCaseCreateRequest(BaseModel):
    case_code: str = Field(min_length=1, max_length=40)
    employee_id: UUID | None = None
    case_type: Literal["grievance", "disciplinary", "whistleblower", "safety", "other"]
    severity: Literal["low", "medium", "high", "critical"] = "medium"
    title: str = Field(min_length=2, max_length=200)
    details: str = Field(min_length=5)


class HrCaseCloseRequest(BaseModel):
    status: Literal["investigating", "action_taken", "closed"]
    resolution_notes: str | None = None


class HrCaseResponse(BaseModel):
    id: UUID
    case_code: str
    employee_id: UUID | None
    case_type: str
    severity: str
    title: str
    details_plain: str | None = None
    status: str
    opened_by_id: UUID | None
    closed_by_id: UUID | None
    closed_at: datetime | None
    resolution_notes: str | None
    created_at: datetime


class HrCaseListResponse(BaseModel):
    items: list[HrCaseResponse]
    total: int


class HrReportFilters(BaseModel):
    project_id: UUID | None = None
    department_id: UUID | None = None
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def validate_window(self) -> "HrReportFilters":
        if (self.date_from is None) != (self.date_to is None):
            raise ValueError("Provide both activity dates or leave both blank.")
        if (
            self.date_from is not None
            and self.date_to is not None
            and self.date_to < self.date_from
        ):
            raise ValueError("The activity end date must be on or after the start date.")
        return self


class HrReportSiteResponse(BaseModel):
    id: UUID
    name: str


class HrReportSiteListResponse(BaseModel):
    items: list[HrReportSiteResponse]
    has_more: bool


class HrReportWindow(BaseModel):
    date_from: date
    date_to: date


class HrSummaryReportResponse(BaseModel):
    as_of: date
    timezone: str
    filters: HrReportFilters
    attendance_window: HrReportWindow
    due_window: HrReportWindow
    total_employees: int
    active_employees: int
    probation_employees: int
    draft_employees: int
    open_requisitions: int
    pending_access_requests: int
    pending_leave_requests: int
    open_onboarding_cases: int
    open_offboarding_cases: int
    open_hr_service_requests: int
    expiring_within_30_days: int
    credentials_due: int
    attendance_exceptions: int
    probation_reviews_due: int
    training_sessions_due: int | None
    separated_employees: int
    by_department: dict[str, int]
    by_employment_status: dict[str, int]
