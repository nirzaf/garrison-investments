from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.utils.time import business_today

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


EmploymentChangeType = Literal[
    "transfer",
    "promotion",
    "category_amendment",
    "contract_renewal",
    "rehire",
    "profile_correction",
]


class EmploymentChangeFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: UUID | None = None
    manager_employee_id: UUID | None = None
    work_location: str | None = Field(default=None, max_length=160)
    position_id: UUID | None = None
    employment_category: EmploymentCategory | None = None
    current_contract_document_id: UUID | None = None
    current_contract_version: int | None = Field(default=None, ge=1)
    renewal_contract_document_id: UUID | None = None
    renewal_contract_version: int | None = Field(default=None, ge=1)
    contract_end_date: date | None = None
    separation_case_id: UUID | None = None
    probation_days: int | None = Field(default=None, ge=1, le=365)
    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    full_name: str | None = Field(default=None, max_length=255)

    @field_validator("first_name", "last_name", "full_name")
    @classmethod
    def validate_corrected_name(cls, value: str | None) -> str:
        if value is None or not value.strip():
            raise ValueError("Enter a nonblank name or omit the unchanged field.")
        return value.strip()


class EmploymentChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_type: EmploymentChangeType
    effective_date: date
    employee_revision: int = Field(ge=1)
    updates: EmploymentChangeFields
    reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def check_changes(self) -> Self:
        keys = self.updates.model_fields_set
        valid = {
            "transfer": {"department_id", "manager_employee_id", "work_location"},
            "promotion": {"position_id"},
            "category_amendment": {"employment_category"},
            "rehire": {"employment_category", "separation_case_id", "probation_days"},
            "profile_correction": {"first_name", "last_name", "full_name"},
            "contract_renewal": {
                "current_contract_document_id",
                "current_contract_version",
                "renewal_contract_document_id",
                "renewal_contract_version",
                "contract_end_date",
            },
        }
        if not keys or not keys <= valid[self.change_type]:
            raise ValueError("Choose fields that match this type of employment change.")
        if self.change_type == "promotion" and self.updates.position_id is None:
            raise ValueError("Select a position for promotion.")
        if self.change_type == "category_amendment" and self.updates.employment_category is None:
            raise ValueError("Select an employment category.")
        if self.change_type == "rehire" and (
            self.updates.separation_case_id is None or self.updates.employment_category is None
        ):
            raise ValueError("Select the completed separation and the new employment category.")
        if self.change_type == "rehire" and (
            (self.updates.employment_category == "probation")
            != (self.updates.probation_days is not None)
        ):
            raise ValueError("Set the probation duration only for probationary rehire.")
        if self.change_type == "contract_renewal":
            if keys != valid["contract_renewal"] or any(
                getattr(self.updates, key) is None for key in keys
            ):
                raise ValueError("Select both exact contract versions and the renewed end date.")
            if (
                self.updates.current_contract_document_id
                == self.updates.renewal_contract_document_id
            ):
                raise ValueError("Select separate contracts with their own recorded expiry dates.")
        if len(self.reason.strip()) < 2:
            raise ValueError("Enter a reason for the proposed change.")
        return self


class EmploymentChangeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


class EmploymentChangeResponse(BaseModel):
    id: UUID
    employee_id: UUID
    change_type: EmploymentChangeType
    effective_date: date
    employee_revision: int
    updates: dict[str, str | int | None]
    reason: str
    status: Literal["proposed", "approved", "rejected", "applied"]
    proposed_by: UUID
    decided_by: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    applied_by: UUID | None
    applied_at: datetime | None
    applied_employee_revision: int | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmploymentChangeListResponse(BaseModel):
    items: list[EmploymentChangeResponse]
    total: int


class DueEmploymentChange(BaseModel):
    id: UUID
    employee_id: UUID
    employee_code: str
    change_type: EmploymentChangeType
    effective_date: date
    revision_matches: bool


class DueEmploymentChangeList(BaseModel):
    as_of: date
    items: list[DueEmploymentChange]
    total: int


class EmploymentPeriodResponse(BaseModel):
    id: UUID
    started_on: date | None
    ended_on: date | None
    separation_case_id: UUID | None
    rehire_change_id: UUID | None
    onboarding_case_id: UUID | None

    model_config = ConfigDict(from_attributes=True)


class EmploymentPeriodListResponse(BaseModel):
    items: list[EmploymentPeriodResponse]
    total: int


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
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
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
    record_revision: int
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
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
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
    expected_updated_at: AwareDatetime | None = None


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
    expected_requisition_updated_at: AwareDatetime | None = None


ApplicationRetentionDecision = Literal["retain_until_review", "policy_review_required"]
ApplicationStage = Literal[
    "applied",
    "screening",
    "shortlisted",
    "interview",
    "evaluation",
    "offer",
    "hired",
    "rejected",
    "withdrawn",
]


class ApplicationWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_stage: Literal[
        "applied", "screening", "shortlisted", "interview", "evaluation", "offer"
    ]
    reason: str = Field(min_length=2, max_length=500)
    retention_decision: ApplicationRetentionDecision
    retention_review_on: date | None = None
    retention_policy_reference: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_review_plan(self) -> Self:
        has_plan = (
            self.retention_review_on is not None or self.retention_policy_reference is not None
        )
        if self.retention_decision == "retain_until_review":
            if self.retention_review_on is None or self.retention_policy_reference is None:
                raise ValueError("Provide the approved policy reference and review date.")
        elif has_plan:
            raise ValueError("Leave the date and policy reference unset until policy review.")
        return self


class ApplicationStageUpdateRequest(BaseModel):
    stage: ApplicationStage
    expected_updated_at: AwareDatetime | None = None
    overall_score: Decimal | None = Field(default=None, max_digits=5, decimal_places=2)
    screening_notes: str | None = None
    rejection_reason: str | None = None
    withdrawal: ApplicationWithdrawalRequest | None = None

    @model_validator(mode="after")
    def validate_withdrawal(self) -> Self:
        if (self.stage == "withdrawn") != (self.withdrawal is not None):
            raise ValueError("The withdrawal plan is required only for a withdrawal.")
        if self.withdrawal is not None and any(
            value is not None
            for value in (self.overall_score, self.screening_notes, self.rejection_reason)
        ):
            raise ValueError("Withdrawals cannot change screening or rejection details.")
        return self


class ApplicationResponse(BaseModel):
    id: UUID
    requisition_id: UUID
    candidate_id: UUID
    stage: str
    overall_score: Decimal | None
    screening_notes: str | None
    rejection_reason: str | None
    withdrawn_at: datetime | None
    withdrawal_reason: str | None
    retention_decision: ApplicationRetentionDecision | None
    retention_review_on: date | None
    retention_policy_reference: str | None
    assigned_recruiter_id: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApplicationListItem(ApplicationResponse):
    candidate_name: str
    candidate_code: str
    position_title: str


class ApplicationListResponse(BaseModel):
    items: list[ApplicationListItem]
    total: int


class ApplicationActivity(BaseModel):
    id: UUID
    stage: str
    actor_name: str | None
    created_at: datetime


class ApplicationActivityList(BaseModel):
    items: list[ApplicationActivity]
    total: int


class InterviewCreateRequest(BaseModel):
    application_id: UUID
    interview_id: UUID | None = None
    expected_application_updated_at: AwareDatetime | None = None
    round_number: int = Field(default=1, ge=1)
    interview_type: str = Field(default="technical", max_length=40)
    scheduled_at: datetime | None = None
    interviewer_user_id: UUID | None = None
    interviewer_name: str | None = Field(default=None, max_length=160)


class InterviewUpdateRequest(BaseModel):
    expected_updated_at: AwareDatetime | None = None
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


class InterviewerOption(BaseModel):
    id: UUID
    full_name: str
    employee_code: str | None = None


class InterviewerOptions(BaseModel):
    items: list[InterviewerOption]
    total: int


class OfferCreateRequest(BaseModel):
    offer_code: str = Field(min_length=1, max_length=40)
    application_id: UUID
    expected_application_updated_at: AwareDatetime | None = None
    document_version_id: UUID | None = None
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
    expected_updated_at: AwareDatetime | None = None
    document_version_id: UUID | None = None
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
    expected_updated_at: AwareDatetime | None = None
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
    document_version_id: UUID | None = None
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
    expected_updated_at: AwareDatetime | None = None


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


class MyPolicyFileResponse(HrDocumentDownloadResponse):
    file_size: int | None
    sha256_checksum: str | None


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


class RosterAllocationCreateRequest(BaseModel):
    id: UUID
    employee_id: UUID
    project_id: UUID
    work_date: date


class RosterCancellationRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    model_config = ConfigDict(str_strip_whitespace=True)


class RosterAllocationResponse(RosterAllocationCreateRequest):
    calendar_id: UUID
    shift_id: UUID | None
    employee_name: str
    project_name: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    planned_hours: Decimal
    created_at: datetime
    cancelled_at: datetime | None
    cancellation_reason: str | None
    model_config = ConfigDict(from_attributes=True)


class RosterAllocationListResponse(BaseModel):
    items: list[RosterAllocationResponse]
    total: int


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
    annual_entitlement_days: Decimal = Field(ge=0, max_digits=5, decimal_places=2)
    accrual_frequency: Literal["annual", "monthly", "manual"] = "annual"
    prorate_by_calendar_day: bool = False
    max_carry_forward_days: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=5, decimal_places=2
    )
    allow_negative_balance: bool = False
    expire_excess_on_rollover: bool = False
    effective_from: date
    effective_to: date
    approve_immediately: bool = False

    @model_validator(mode="after")
    def validate_proration(self) -> Self:
        if self.prorate_by_calendar_day and self.accrual_frequency == "manual":
            raise ValueError("Calendar-day proration requires monthly or annual accrual.")
        return self


class LeavePolicyDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=500)


class LeavePolicyResponse(BaseModel):
    id: UUID
    code: str
    name: str
    leave_type_id: UUID
    employment_category: str | None
    annual_entitlement_days: Decimal
    accrual_frequency: str
    prorate_by_calendar_day: bool
    max_carry_forward_days: Decimal
    allow_negative_balance: bool
    expire_excess_on_rollover: bool
    status: Literal["legacy", "draft", "approved", "rejected"]
    effective_from: date | None
    effective_to: date | None
    created_by_id: UUID | None
    rejection_reason: str | None
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


class LeaveAccrualRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    year: int = Field(ge=2020, le=2100)
    month: int | None = Field(default=None, ge=1, le=12)


class LeaveAccrualApplyRequest(LeaveAccrualRequest):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LeaveAccrualResponse(BaseModel):
    employee_id: UUID
    leave_type_id: UUID
    policy_id: UUID
    period_start: date
    period_end: date
    eligible_from: date | None = None
    eligible_through: date | None = None
    days: Decimal
    digest: str | None = None
    ledger_entry_id: UUID | None = None


class LeaveAccrualCatchUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    year: int = Field(ge=2020, le=2100)
    start_month: int = Field(ge=1, le=12)
    end_month: int = Field(ge=1, le=12)


class LeaveAccrualCatchUpApplyRequest(LeaveAccrualCatchUpRequest):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LeaveAccrualCatchUpResponse(BaseModel):
    periods: list[LeaveAccrualResponse]
    pending_days: Decimal
    digest: str | None = None


class LeaveRolloverRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    leave_type_id: UUID
    source_year: int = Field(ge=2020, le=2099)


class LeaveRolloverApplyRequest(LeaveRolloverRequest):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LeaveRolloverResponse(BaseModel):
    employee_id: UUID
    leave_type_id: UUID
    policy_id: UUID
    source_year: int
    target_year: int
    source_balance: Decimal
    carried_days: Decimal
    expired_days: Decimal
    digest: str | None = None
    receipt_id: UUID | None = None


class LeaveBalanceItem(BaseModel):
    leave_type_id: UUID
    leave_type_code: str
    leave_type_name: str
    leave_year: int
    balance_days: Decimal


class LeaveBalanceListResponse(BaseModel):
    employee_id: UUID
    items: list[LeaveBalanceItem]


class LeaveUnitsQuery(BaseModel):
    leave_type_id: UUID
    start_date: date
    end_date: date
    is_half_day: bool = False
    half_day_period: Literal["morning", "afternoon"] | None = None


class LeaveUnitsResponse(BaseModel):
    days_requested: Decimal


class LeaveRequestFields(LeaveUnitsQuery):
    days_requested: Decimal | None = Field(default=None, gt=0, max_digits=6, decimal_places=2)
    reason: str | None = None
    attachment_document_id: UUID | None = None


class LeaveRequestCreateRequest(LeaveRequestFields):
    employee_id: UUID | None = None
    submit_immediately: bool = True


class LeaveRequestResubmitRequest(LeaveRequestFields):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)


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


class LeaveDateEvidenceDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_dates: list[date] = Field(min_length=1, max_length=366)
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")

    @field_validator("work_dates")
    @classmethod
    def unique_work_dates(cls, value: list[date]) -> list[date]:
        if len(value) != len(set(value)):
            raise ValueError("Supply each historical work date once.")
        return sorted(value)


class LeaveDateEvidenceCreate(LeaveDateEvidenceDetail):
    proposal_id: UUID
    expected_revision: int = Field(ge=1)


class LeaveDateEvidenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LeaveDateEvidenceResponse(LeaveDateEvidenceDetail):
    id: UUID
    request_revision: int
    status: str
    digest: str
    submitted_by_id: UUID
    decided_by_id: UUID | None
    created_at: datetime
    decided_at: datetime | None


class LeaveDateEvidenceCandidate(BaseModel):
    request_id: UUID
    employee_id: UUID
    start_date: date
    end_date: date
    approved_units: Decimal
    requires_payroll_correction: bool


class LeaveDateEvidenceCandidates(BaseModel):
    items: list[LeaveDateEvidenceCandidate]
    total: int


class LeaveDateEvidencePage(BaseModel):
    request_id: UUID
    request_revision: int
    start_date: date
    end_date: date
    approved_units: Decimal
    scheduled_work_dates: list[date] | None
    requires_payroll_correction: bool
    can_propose: bool
    can_review: bool
    items: list[LeaveDateEvidenceResponse]
    total: int


# --- Policies, Letter Templates, HR Service Requests ---


class PolicyDocumentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    version: str = Field(default="1.0", min_length=1, max_length=20)
    effective_date: date
    content_summary: str = Field(min_length=5)
    document_id: UUID | None = None
    document_version_number: int | None = Field(default=None, ge=1)
    supersedes_policy_id: UUID | None = None
    requires_acknowledgement: bool = True

    @model_validator(mode="after")
    def check_policy_asset(self) -> Self:
        if (self.document_id is None) != (self.document_version_number is None):
            raise ValueError("Select the exact approved document version or publish a text policy.")
        return self


class PolicyDocumentResponse(BaseModel):
    id: UUID
    code: str
    title: str
    version: str
    effective_date: date
    content_summary: str
    document_id: UUID | None
    document_version_number: int | None
    supersedes_policy_id: UUID | None
    requires_acknowledgement: bool
    is_active: bool
    published_by_id: UUID | None
    published_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PolicyDocumentListResponse(BaseModel):
    items: list[PolicyDocumentResponse]
    total: int


class MyPolicyResponse(PolicyDocumentResponse):
    is_current: bool
    acknowledged_at: datetime | None


class MyPolicyListResponse(BaseModel):
    items: list[MyPolicyResponse]
    total: int


class PolicyAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_version: str = Field(min_length=1, max_length=20)
    expected_document_version: int | None = Field(default=None, ge=1)
    notes: str | None = None


class PolicyAcknowledgementResponse(BaseModel):
    id: UUID
    policy_id: UUID
    employee_id: UUID
    acknowledged_at: datetime
    acknowledged_by_user_id: UUID | None
    notes: str | None
    policy_version: str
    document_version_number: int | None

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
        "candidate_rejection",
        "custom",
    ]
    subject_template: str = Field(min_length=2, max_length=255)
    body_template: str = Field(min_length=5, max_length=12000)
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
    extra_vars: dict[str, str] = Field(default_factory=dict, max_length=32)


class LetterRenderResponse(BaseModel):
    template_id: UUID
    employee_id: UUID
    subject: str
    body: str
    digest: str | None = None


class LetterDraftRequest(LetterGenerateRequest):
    draft_id: UUID
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class LetterDecisionRequest(BaseModel):
    decision: Literal["issued", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)


class LetterSummary(BaseModel):
    id: UUID
    template_name: str
    status: str
    can_decide: bool = False
    created_at: datetime
    decided_at: datetime | None


class LetterListResponse(BaseModel):
    items: list[LetterSummary]
    total: int


class LetterDetail(LetterSummary):
    subject: str
    body: str
    rejection_reason: str | None = None


class CandidateCorrespondenceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: UUID
    template_id: UUID


class CandidateCorrespondenceDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str | None = Field(default=None, max_length=2000)


class CandidateCorrespondenceDetail(LetterDetail):
    digest: str


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
    generated_letter_id: UUID | None = None
    expected_updated_at: AwareDatetime | None = None


class HrServiceRequestAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_to_id: UUID
    expected_updated_at: AwareDatetime
    reason: str = Field(min_length=1, max_length=500)


class HrServiceRequestAssignee(BaseModel):
    id: UUID
    full_name: str


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
    generated_letter_id: UUID | None
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


OffboardingCustodyArea = Literal["store_inventory", "it_admin"]


class OffboardingCustodyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    kind: Literal["returned", "cleared", "waived", "flagged"]
    area: OffboardingCustodyArea = "store_inventory"
    movement_id: UUID | None = None
    device_reference: str | None = Field(
        default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$"
    )
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")

    @model_validator(mode="after")
    def check_evidence(self) -> Self:
        if self.area == "store_inventory":
            if self.device_reference is not None or (
                (self.kind == "returned") != (self.movement_id is not None)
            ):
                raise ValueError("Only a store return uses a posted movement ID.")
        elif self.movement_id is not None or (
            (self.kind != "cleared") != (self.device_reference is not None)
        ):
            raise ValueError("IT device events require a device reference. IT sign-off omits it.")
        if self.device_reference is not None:
            self.device_reference = self.device_reference.upper()
        return self


class OffboardingCustodyResponse(BaseModel):
    id: UUID
    case_id: UUID
    area: OffboardingCustodyArea
    kind: str
    movement_id: UUID | None
    device_reference: str | None
    evidence_reference: str
    recorded_by_id: UUID
    recorded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OffboardingCustodyListResponse(BaseModel):
    items: list[OffboardingCustodyResponse]
    total: int
    clearance_status: str
    case_closed: bool
    outstanding_devices: int


SettlementOutcome = Literal["outstanding", "settled", "nothing_due"]
SettlementDecision = Literal["approved", "rejected"]


class SeparationSettlementProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    expected_record_id: UUID | None
    outcome: SettlementOutcome
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class SeparationSettlementReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: SettlementDecision
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class SeparationSettlementResponse(BaseModel):
    id: UUID
    outcome: SettlementOutcome
    status: Literal["proposed", "approved", "rejected"]
    evidence_reference: str
    proposed_by_id: UUID
    created_at: datetime
    reviewed_by_id: UUID | None
    reviewed_at: datetime | None
    review_reference: str | None

    model_config = ConfigDict(from_attributes=True)


class SeparationSettlementListResponse(BaseModel):
    items: list[SeparationSettlementResponse]
    total: int
    case_closed: bool
    clearance_status: str
    current_record_id: UUID | None


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
    rating_scale: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def check_dates(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("Cycle end cannot precede its start.")
        labels = [label.strip() for label in self.rating_scale]
        if (
            any(not label or len(label) > 60 for label in labels)
            or len({label.casefold() for label in labels}) != len(labels)
            or len(labels) == 1
        ):
            raise ValueError("Enter 2–12 distinct rating labels, or leave the scale empty.")
        self.rating_scale = labels
        return self


class ReviewCycleResponse(BaseModel):
    id: UUID
    code: str
    name: str
    start_date: date
    end_date: date
    rating_scale: list[str]
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


PerformanceAction = Literal[
    "acknowledge_goals",
    "record_progress",
    "submit_self_review",
    "submit_manager_review",
    "calibrate",
    "acknowledge_final",
    "add_addendum",
    "reassign_manager",
]
PerformanceParticipant = Literal["employee", "manager", "hr"]


class PerformanceReviewActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_id: UUID
    expected_revision: int = Field(ge=0)
    action: PerformanceAction
    notes: str | None = Field(default=None, max_length=4000)
    rating: str | None = Field(default=None, max_length=60)
    replacement_reviewer_id: UUID | None = None

    @model_validator(mode="after")
    def require_notes(self) -> Self:
        if self.action not in {"acknowledge_goals", "acknowledge_final"} and not self.notes:
            raise ValueError("Provide notes for this review action.")
        if (self.action == "reassign_manager") != (self.replacement_reviewer_id is not None):
            raise ValueError("Only a manager handoff requires a replacement reviewer.")
        if self.rating is not None and (
            not self.rating
            or self.action not in {"submit_self_review", "submit_manager_review", "calibrate"}
        ):
            raise ValueError(
                "A rating is available only on the assessment and calibration actions."
            )
        return self


class PerformanceEventResponse(BaseModel):
    id: UUID
    revision: int
    action: PerformanceAction
    participant: PerformanceParticipant
    actor_id: UUID
    notes: str | None
    rating: str | None
    previous_reviewer_id: UUID | None
    replacement_reviewer_id: UUID | None
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PerformanceReviewItem(BaseModel):
    id: UUID
    cycle_name: str
    employee_name: str
    status: str
    participant: PerformanceParticipant


class PerformanceReviewQueue(BaseModel):
    items: list[PerformanceReviewItem]
    total: int


class PerformanceReviewDetail(PerformanceReviewItem):
    revision: int
    allowed_actions: list[PerformanceAction]
    rating_scale: list[str]
    replacement_reviewer_id: UUID | None = None
    replacement_reviewer_name: str | None = None
    goals: list[GoalResponse]
    events: list[PerformanceEventResponse]


class TrainingCourseCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=2, max_length=200)
    category: str = Field(default="safety", max_length=60)
    provider: str | None = Field(default=None, max_length=160)
    duration_hours: Decimal | None = Field(default=None, gt=0, max_digits=5, decimal_places=2)
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


class TrainingRequirementCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    position_id: UUID | None = None
    project_id: UUID | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.position_id is None and self.project_id is None:
            raise ValueError("Select a job position, a project site, or both.")
        return self


class TrainingRequirementResponse(TrainingRequirementCreateRequest):
    id: UUID
    is_active: bool
    course_title: str
    position_title: str | None
    project_name: str | None


class TrainingRequirementListResponse(BaseModel):
    items: list[TrainingRequirementResponse]
    total: int


class TrainingRequirementStatus(BaseModel):
    course_id: UUID
    course_title: str
    status: Literal["met", "enrolled", "expired", "required"]


class TrainingRequirementStatusListResponse(BaseModel):
    items: list[TrainingRequirementStatus]
    total: int


class TrainingEnrollmentCreateRequest(BaseModel):
    course_id: UUID
    employee_id: UUID
    scheduled_date: date | None = None


class TrainingEnrollmentUpdateRequest(BaseModel):
    status: Literal["enrolled", "in_progress", "completed", "no_show", "cancelled"]
    completed_date: date | None = None
    score: Decimal | None = None


class TrainingCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: UUID
    version_number: int = Field(ge=1)
    completed_date: date
    score: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)


class TrainingCompletionResponse(BaseModel):
    enrollment_id: UUID
    certificate_id: UUID
    document_id: UUID
    version_number: int
    completed_date: date
    score: Decimal | None
    verified_by_id: UUID
    verified_at: datetime


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


class SelfTrainingItem(BaseModel):
    enrollment_id: UUID
    course_title: str
    status: str
    scheduled_date: date | None
    completed_date: date | None
    verified: bool
    certificate_expiry: date | None
    certificate_expired: bool


class SelfTrainingListResponse(BaseModel):
    items: list[SelfTrainingItem]
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def effective_status(self) -> str:
        if self.status in {"valid", "expiring"} and self.expiry_date is not None:
            if self.expiry_date < business_today():
                return "expired"
        return self.status


class CertificationListResponse(BaseModel):
    items: list[CertificationResponse]
    total: int


class BenefitTypeCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    category: str = Field(min_length=2, max_length=40)
    requires_policy_approval: bool = True
    reimbursement_ceiling: Decimal | None = Field(
        default=None, gt=0, max_digits=15, decimal_places=2
    )
    reimbursement_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    allows_advances: bool = False


class BenefitTypeResponse(BaseModel):
    id: UUID
    code: str
    name: str
    category: str
    requires_policy_approval: bool
    is_active: bool
    reimbursement_ceiling: Decimal | None
    reimbursement_currency: str | None
    allows_advances: bool
    proposed_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
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
    benefit_assignment_id: UUID
    claim_date: date
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(default="LKR", pattern=r"^[A-Z]{3}$")
    description: str = Field(min_length=2, max_length=2000)
    receipt_document_id: UUID
    receipt_version_number: int = Field(ge=1)


class ReimbursementDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected", "paid", "cancelled"]
    notes: str | None = Field(default=None, max_length=1000)
    settlement_reference: str | None = Field(default=None, min_length=1, max_length=100)
    expected_payable_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    settled_amount: Decimal | None = Field(default=None, gt=0, max_digits=15, decimal_places=2)
    settled_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class ReimbursementPayable(BaseModel):
    version: Literal["reimbursement-payable-v1"] = "reimbursement-payable-v1"
    claim_id: UUID
    payable_reference: str
    employee_id: UUID
    amount: Decimal
    currency: str
    approved_at: datetime


class ReimbursementPayableResponse(BaseModel):
    reference: ReimbursementPayable
    reference_sha256: str
    status: Literal["approved", "paid"]


class ReimbursementResponse(BaseModel):
    id: UUID
    claim_code: str
    employee_id: UUID
    claim_type: str
    benefit_assignment_id: UUID | None
    claim_date: date
    amount: Decimal
    currency: str
    description: str
    receipt_document_id: UUID | None
    receipt_version_id: UUID | None
    settlement_reference: str | None
    status: str
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ReimbursementListResponse(BaseModel):
    items: list[ReimbursementResponse]
    total: int


class ReimbursementOperatorResponse(ReimbursementResponse):
    submitted_by_id: UUID | None


class ReimbursementOperatorListResponse(BaseModel):
    items: list[ReimbursementOperatorResponse]
    total: int


class EmployeeAdvanceRequest(BaseModel):
    employee_id: UUID
    benefit_assignment_id: UUID
    requested_on: date
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class EmployeeAdvanceDecision(BaseModel):
    decision: Literal["approved", "rejected", "cancelled"]


class EmployeeAdvancePayment(BaseModel):
    reference: str = Field(min_length=1, max_length=100)
    occurred_on: date
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class EmployeeAdvanceDisbursement(EmployeeAdvancePayment):
    expected_payable_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EmployeeAdvanceRecovery(BaseModel):
    reference: str
    occurred_on: date
    amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class EmployeeAdvanceResponse(BaseModel):
    id: UUID
    employee_id: UUID
    benefit_assignment_id: UUID
    requested_on: date
    amount: Decimal
    currency: str
    status: str
    submitted_by_id: UUID
    decided_by_id: UUID | None
    decided_at: datetime | None
    payable_sha256: str | None
    disbursed_on: date | None
    disbursement_reference: str | None
    recovered: Decimal
    outstanding: Decimal
    recoveries: list[EmployeeAdvanceRecovery]


class EmployeeAdvanceListResponse(BaseModel):
    items: list[EmployeeAdvanceResponse]
    total: int


class CompensationTermCreateRequest(BaseModel):
    employee_id: UUID
    effective_from: date
    pay_frequency: Literal["monthly", "biweekly", "weekly", "daily"] = "monthly"
    currency: str = Field(default="LKR", pattern=r"^[A-Z]{3}$")
    base_salary: str = Field(pattern=r"^[0-9]{1,16}(\.[0-9]{1,2})?$")
    allowances_json: dict[str, Any] | None = None


class CompensationTermDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=1000)


class CompensationTermResponse(BaseModel):
    id: UUID
    employee_id: UUID
    effective_from: date
    pay_frequency: str
    currency: str
    base_salary_masked: str
    base_salary_plain: str | None = None
    allowances_json: dict[str, Any] | None = None
    is_current: bool
    approval_status: str
    proposed_by_id: UUID | None
    rejection_reason: str | None = None
    approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime


class CompensationTermListResponse(BaseModel):
    items: list[CompensationTermResponse]
    total: int


class PayrollPolicyWorkedExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_salary: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    earnings: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)
    extra_deductions: Decimal = Field(
        default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2
    )
    expected_gross: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    expected_deductions: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    expected_net: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class PayrollControlledPolicyRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
    version: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
    effective_from: date
    approval_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
    worked_examples: list[PayrollPolicyWorkedExample] = Field(min_length=1, max_length=12)


class PayrollPolicyCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=2, max_length=160)
    rules_json: dict[str, Any] = Field(default_factory=dict)
    controlled_record: PayrollControlledPolicyRecord | None = None


class PayrollPolicyDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    rules_json: dict[str, Any]
    controlled_record: PayrollControlledPolicyRecord
    expected_updated_at: datetime


class PayrollPolicyApproveRequest(BaseModel):
    expected_updated_at: datetime


class PayrollPolicyResponse(BaseModel):
    id: UUID
    code: str
    name: str
    rules_json: dict[str, Any]
    controlled_record: PayrollControlledPolicyRecord | None = None
    is_approved: bool
    approved_by_id: UUID | None
    second_approved_by_id: UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime

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


class PayrollRunCalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    employee_ids: list[UUID] = Field(min_length=1, max_length=1000)

    @field_validator("employee_ids")
    @classmethod
    def unique_roster(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Each employee may appear only once.")
        return value


class PayrollSourceEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    leave_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollSnapshotCalculateRequest(PayrollRunCalculateRequest):
    source_evidence: PayrollSourceEvidenceRequest | None = None


class PayrollRunApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollTimeDownloadRequest(PayrollRunCalculateRequest):
    expected_csv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


PayrollTimeIssueCode = Literal[
    "missing_locked_timesheet",
    "timesheet_crosses_period",
    "timesheet_not_locked",
    "overlapping_timesheets",
    "pending_attendance",
    "attendance_without_schedule",
    "attendance_without_timesheet",
    "pending_attendance_correction",
    "pending_overtime",
    "overtime_without_timesheet",
    "duplicate_approved_overtime",
    "overtime_hours_mismatch",
]


class PayrollTimeInputIssue(BaseModel):
    employee_id: UUID
    record_id: UUID | None = None
    code: PayrollTimeIssueCode


class PayrollTimeInputPreview(BaseModel):
    payroll_period_id: UUID
    period_start: date
    period_end: date
    employee_count: int
    timesheet_count: int
    regular_hours: Decimal | None
    overtime_hours: Decimal | None
    csv_sha256: str | None
    issues: list[PayrollTimeInputIssue]


PayrollLeaveIssueCode = Literal[
    "pending_leave",
    "leave_crosses_period",
    "leave_ledger_mismatch",
    "leave_work_dates_mismatch",
    "overlapping_leave",
]


class PayrollLeaveInputIssue(BaseModel):
    employee_id: UUID
    request_id: UUID
    code: PayrollLeaveIssueCode


class PayrollLeaveInputPreview(BaseModel):
    payroll_period_id: UUID
    period_start: date
    period_end: date
    employee_count: int
    approved_request_count: int
    paid_days: Decimal | None
    unpaid_days: Decimal | None
    csv_sha256: str | None
    issues: list[PayrollLeaveInputIssue]


class PayrollAdjustmentDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["earning", "deduction"]
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$")
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class PayrollAdjustmentCreate(PayrollAdjustmentDetail):
    adjustment_id: UUID
    employee_id: UUID


class PayrollAdjustmentReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollAdjustmentResponse(PayrollAdjustmentDetail):
    id: UUID
    employee_id: UUID
    status: str
    submitted_by_id: UUID
    decided_by_id: UUID | None
    decided_at: datetime | None
    digest: str


class PayrollAdjustmentList(BaseModel):
    run_id: UUID
    can_submit: bool
    can_review: bool
    items: list[PayrollAdjustmentResponse]


class PayrollSnapshotLine(BaseModel):
    employee_id: UUID
    payment_reference: UUID
    term_id: UUID
    adjustments: list[PayrollAdjustmentResponse] = Field(default_factory=list)
    gross: Decimal
    deductions: Decimal
    net: Decimal


class PayrollFrozenSources(PayrollSourceEvidenceRequest):
    regular_hours: Decimal
    overtime_hours: Decimal
    paid_days: Decimal
    unpaid_days: Decimal


class PayrollRunSnapshotResponse(BaseModel):
    run_id: UUID
    status: str
    prepared_by_id: UUID | None
    approved_by_id: UUID | None
    payslips_published_at: datetime | None
    closed_at: datetime | None = None
    digest: str
    policy_id: UUID
    controlled_policy_record: PayrollControlledPolicyRecord | None = None
    period_start: date
    period_end: date
    pay_date: date
    calculation_basis: Literal["base_salary_only", "base_salary_with_reviewed_adjustments"]
    currency: str
    rounding: str
    employee_deduction_rate: Decimal
    source_evidence: PayrollFrozenSources | None = None
    lines: list[PayrollSnapshotLine]
    gross: Decimal
    deductions: Decimal
    net: Decimal


class PayrollExportConfirmRequest(PayrollRunApproveRequest):
    expected_csv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollExportReceipt(BaseModel):
    run_id: UUID
    snapshot_digest: str
    csv_sha256: str
    format_version: int
    exported_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PayrollExportPreview(BaseModel):
    run_id: UUID
    snapshot_digest: str
    csv_sha256: str
    format_version: int
    currency: str
    pay_date: date
    payment_count: int
    zero_net_count: int
    gross: Decimal
    deductions: Decimal
    net: Decimal
    receipt: PayrollExportReceipt | None = None


class PayrollSettlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    payment_reference: UUID
    expected_csv_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: Literal["paid", "failed", "reversed"]
    amount: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$")
    occurred_on: date
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")
    reverses_event_id: UUID | None = None

    @model_validator(mode="after")
    def validate_event(self) -> Self:
        if (self.kind == "reversed") != (self.reverses_event_id is not None):
            raise ValueError("Only a reversal references an original payment event.")
        if (self.kind == "failed") != (Decimal(self.amount) == 0):
            raise ValueError(
                "Failed events have zero amount; other events require a positive amount."
            )
        return self


class PayrollSettlementEventResponse(BaseModel):
    id: UUID
    run_id: UUID
    payment_reference: UUID
    kind: Literal["paid", "failed", "reversed"]
    amount: Decimal
    occurred_on: date
    evidence_reference: str
    reverses_event_id: UUID | None
    recorded_at: datetime


class PayrollSettlementEventsResponse(BaseModel):
    items: list[PayrollSettlementEventResponse]
    total: int


class PayrollSettlementLine(BaseModel):
    payment_reference: UUID
    expected: Decimal
    net_paid: Decimal
    outstanding: Decimal
    status: Literal["pending", "failed", "partial", "settled", "reversed"]


class PayrollClosureRequest(PayrollExportConfirmRequest):
    expected_settlement_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollClosureResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: UUID
    closed_by_id: UUID
    snapshot_digest: str
    csv_sha256: str
    settlement_digest: str
    closed_at: datetime


class PayrollCorrectionCreate(PayrollRunApproveRequest):
    correction_id: UUID
    expected_previous_id: UUID | None
    gross: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$")
    deductions: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,2})?$")
    evidence_reference: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")


class PayrollCorrectionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class PayrollCorrectionAmounts(BaseModel):
    gross: Decimal
    deductions: Decimal
    net: Decimal


class PayrollCorrectionResponse(BaseModel):
    id: UUID
    line_id: UUID
    previous_id: UUID | None
    snapshot_digest: str
    digest: str
    status: str
    currency: str
    baseline: PayrollCorrectionAmounts
    proposed: PayrollCorrectionAmounts
    net_delta: Decimal
    evidence_reference: str
    submitted_by_id: UUID
    decided_by_id: UUID | None
    created_at: datetime
    decided_at: datetime | None


class PayrollCorrectionPage(BaseModel):
    line_id: UUID
    currency: str
    current_correction_id: UUID | None
    baseline: PayrollCorrectionAmounts
    items: list[PayrollCorrectionResponse]
    total: int


class PayrollSettlementSummary(BaseModel):
    run_id: UUID
    csv_sha256: str
    currency: str
    expected: Decimal
    net_paid: Decimal
    outstanding: Decimal
    fully_reconciled: bool
    settlement_digest: str
    closure: PayrollClosureResponse | None = None
    payments: list[PayrollSettlementLine]


class PayslipPublicationResponse(BaseModel):
    run_id: UUID
    published_at: datetime
    snapshot_digest: str

    model_config = ConfigDict(from_attributes=True)


class PayslipSummary(BaseModel):
    run_id: UUID
    period_start: date
    period_end: date
    pay_date: date
    published_at: datetime


class PayslipListResponse(BaseModel):
    items: list[PayslipSummary]
    total: int


class PayslipDetail(PayslipSummary):
    currency: str
    gross: Decimal
    deductions: Decimal
    net: Decimal


class PayrollRunResponse(BaseModel):
    id: UUID
    payroll_period_id: UUID
    policy_id: UUID | None
    status: str
    prepared_by_id: UUID | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    snapshot_digest: str | None
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
