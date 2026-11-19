from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BoqItemCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    discipline: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=100)
    milestone_name: str | None = Field(default=None, max_length=150)
    unit: str = Field(min_length=1, max_length=20)
    planned_quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    unit_rate: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class MilestoneCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=150)
    discipline: str | None = Field(default=None, max_length=50)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    sort_order: int = Field(default=0, ge=0, le=2_147_483_647)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=2, max_length=200)
    scope_of_work: str = Field(min_length=1)
    target_end_date: date
    location: str | None = None
    description: str | None = None
    status: str = Field(default="planning", min_length=1)
    budget_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    start_date: date | None = None
    client_name: str | None = Field(default=None, max_length=200)
    contract_number: str | None = Field(default=None, max_length=50)
    milestones: list[MilestoneCreateRequest] = Field(default_factory=list)
    boq_items: list[BoqItemCreateRequest] = Field(min_length=1)


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    scope_of_work: str | None = Field(default=None, min_length=1)
    target_end_date: date | None = None
    location: str | None = None
    description: str | None = None
    status: str | None = Field(default=None, min_length=1)
    budget_amount: Decimal | None = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    start_date: date | None = None
    actual_end_date: date | None = None
    client_name: str | None = Field(default=None, max_length=200)
    contract_number: str | None = Field(default=None, max_length=50)

    @field_validator("name", "scope_of_work", "target_end_date", "status", mode="before")
    @classmethod
    def require_non_null_field(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be cleared.")
        return value


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    code: str
    location: str | None
    description: str | None
    scope_of_work: str
    status: str
    budget_amount: Decimal | None
    start_date: date | None
    target_end_date: date
    actual_end_date: date | None
    client_name: str | None
    contract_number: str | None
    progress_percentage: Decimal
    revision: int
    created_by: UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int


class ProjectOption(BaseModel):
    id: UUID
    name: str
    code: str

    model_config = ConfigDict(from_attributes=True)


class ProjectOptionListResponse(BaseModel):
    items: list[ProjectOption]
    total: int


class ProjectMemberCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    user_id: UUID
    role_in_project: str | None = Field(default=None, max_length=50)
    expected_revision: int | None = Field(default=None, ge=1)


class ProjectMemberResponse(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    user_name: str | None = None
    role_in_project: str | None
    assigned_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectMemberRevocationResponse(BaseModel):
    project_id: UUID
    user_id: UUID
    revision: int


class MilestoneResponse(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    discipline: str | None
    planned_start_date: date | None
    planned_end_date: date | None
    actual_start_date: date | None
    actual_end_date: date | None
    progress_percentage: Decimal
    status: str
    sort_order: int

    model_config = ConfigDict(from_attributes=True)


class BoqItemResponse(BaseModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID | None
    item_code: str
    description: str
    discipline: str | None
    phase: str | None
    unit: str
    planned_quantity: Decimal
    approved_quantity: Decimal
    unit_rate: Decimal | None
    planned_amount: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class ProjectTaskCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=180)
    milestone_id: UUID | None = None
    dependency_task_id: UUID | None = None
    owner_id: UUID | None = None
    baseline_start_date: date | None = None
    baseline_end_date: date | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    status: str = Field(default="not_started", min_length=1)
    progress_percentage: Decimal = Field(default=Decimal("0"), ge=0, le=100, decimal_places=2)
    delay_reason: str | None = None
    sort_order: int = Field(default=0, ge=0, le=2_147_483_647)


class ProjectTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=180)
    milestone_id: UUID | None = None
    dependency_task_id: UUID | None = None
    owner_id: UUID | None = None
    baseline_start_date: date | None = None
    baseline_end_date: date | None = None
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    actual_start_date: date | None = None
    actual_end_date: date | None = None
    status: str | None = Field(default=None, min_length=1)
    progress_percentage: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    delay_reason: str | None = None
    sort_order: int | None = Field(default=None, ge=0, le=2_147_483_647)

    @field_validator("name", "status", "progress_percentage", "sort_order", mode="before")
    @classmethod
    def require_non_null_field(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be cleared.")
        return value


class ProjectTaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    milestone_id: UUID | None
    dependency_task_id: UUID | None
    owner_id: UUID | None
    name: str
    baseline_start_date: date | None
    baseline_end_date: date | None
    planned_start_date: date | None
    planned_end_date: date | None
    actual_start_date: date | None
    actual_end_date: date | None
    status: str
    progress_percentage: Decimal
    delay_reason: str | None
    sort_order: int
    revision: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(ProjectResponse):
    members: list[ProjectMemberResponse]
    milestones: list[MilestoneResponse]
    boq_items: list[BoqItemResponse]
    is_read_only: bool


class ProjectTimelineResponse(BaseModel):
    project: ProjectResponse
    milestones: list[MilestoneResponse]
    tasks: list[ProjectTaskResponse]
    owner_names: dict[UUID, str]
