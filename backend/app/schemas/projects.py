from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BoqItemCreateRequest(BaseModel):
    item_code: str = Field(min_length=1, max_length=50)
    description: str = Field(min_length=1)
    discipline: str | None = Field(default=None, max_length=50)
    phase: str | None = Field(default=None, max_length=100)
    milestone_name: str | None = Field(default=None, max_length=150)
    unit: str = Field(min_length=1, max_length=20)
    planned_quantity: Decimal = Field(gt=0)
    unit_rate: Decimal = Field(ge=0)

class MilestoneCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    discipline: str | None = Field(default=None, max_length=50)
    planned_start_date: date | None = None
    planned_end_date: date | None = None
    sort_order: int = Field(default=0, ge=0)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    scope_of_work: str = Field(min_length=1)
    target_end_date: date
    location: str | None = None
    description: str | None = None
    status: str = "planning"
    budget_amount: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    client_name: str | None = Field(default=None, max_length=200)
    contract_number: str | None = Field(default=None, max_length=50)
    milestones: list[MilestoneCreateRequest] = Field(default_factory=list)
    boq_items: list[BoqItemCreateRequest] = Field(min_length=1)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    scope_of_work: str | None = Field(default=None, min_length=1)
    target_end_date: date | None = None
    location: str | None = None
    description: str | None = None
    status: str | None = None
    budget_amount: Decimal | None = Field(default=None, ge=0)
    start_date: date | None = None
    actual_end_date: date | None = None
    client_name: str | None = Field(default=None, max_length=200)
    contract_number: str | None = Field(default=None, max_length=50)


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
    created_by: UUID | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int


class ProjectMemberCreateRequest(BaseModel):
    user_id: UUID
    role_in_project: str | None = Field(default=None, max_length=50)


class ProjectMemberResponse(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    role_in_project: str | None
    assigned_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    unit_rate: Decimal
    planned_amount: Decimal

    model_config = ConfigDict(from_attributes=True)


class ProjectDetailResponse(ProjectResponse):
    members: list[ProjectMemberResponse]
    milestones: list[MilestoneResponse]
    boq_items: list[BoqItemResponse]
    is_read_only: bool


class ProjectTimelineResponse(BaseModel):
    project: ProjectResponse
    milestones: list[MilestoneResponse]
