from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AttachmentRef(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="photo", max_length=30)


class SupervisorUpdateCreateRequest(BaseModel):
    project_id: UUID
    update_date: date
    day_type: str = "weekday"
    work_location: str = Field(min_length=1, max_length=255)
    attendance_count: int = Field(ge=0)
    overtime_hours: Decimal = Field(default=Decimal("0"), ge=0)
    progress_notes: str = Field(min_length=1)
    delay_notes: str | None = None
    required_notes: str = Field(min_length=1)
    attachment_refs: list[AttachmentRef] = Field(default_factory=list)
    activity_scope: str | None = Field(default=None, max_length=2000)
    remaining_work: str | None = Field(default=None, max_length=2000)
    completed_area: str | None = Field(default=None, max_length=255)
    completed_quantity: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=3)
    quantity_unit: str | None = Field(default=None, min_length=1, max_length=30)
    progress_percentage: Decimal | None = Field(default=None, ge=0, le=100, decimal_places=2)
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def check_quantity_unit(self) -> Self:
        if (self.completed_quantity is None) != (not (self.quantity_unit or "").strip()):
            raise ValueError("Enter both the completed quantity and its unit.")
        return self


class SupervisorUpdateCorrectionRequest(SupervisorUpdateCreateRequest):
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=2000)


class SupervisorUpdateSubmitRequest(BaseModel):
    notes: str | None = None
    expected_revision: int = Field(ge=1)


class SupervisorUpdateDecisionRequest(BaseModel):
    expected_submission_revision: int = Field(ge=1)
    stage: Literal["qs", "engineer"]
    decision: Literal["approved", "returned", "rejected"]
    comments: str | None = Field(default=None, max_length=2000)


class SupervisorUpdateResponse(BaseModel):
    previous_id: UUID | None = None
    id: UUID
    project_id: UUID
    supervisor_id: UUID
    update_date: date
    day_type: str
    work_location: str
    attendance_count: int
    overtime_hours: Decimal
    progress_notes: str
    delay_notes: str | None
    required_notes: str
    attachment_refs: list[dict]
    status: str
    submitted_at: datetime | None
    verified_by: UUID | None
    verified_at: datetime | None
    eligible_for_report: bool = False
    verified_report_id: UUID | None
    verified_by_name: str | None = None
    verification_notes: str | None
    activity_scope: str | None = None
    remaining_work: str | None = None
    completed_area: str | None = None
    completed_quantity: Decimal | None = None
    quantity_unit: str | None = None
    progress_percentage: Decimal | None = None
    revision: int = 1
    submission_revision: int | None = None
    pending_reviewer_id: UUID | None = None

    model_config = ConfigDict(from_attributes=True)


class SupervisorUpdateListResponse(BaseModel):
    items: list[SupervisorUpdateResponse]
    total: int


class SupervisorUpdateSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_revision: int
    requirements: SupervisorUpdateCreateRequest
    evidence_ids: list[UUID]
    created_at: datetime
    engineer_id: UUID
    qs_id: UUID | None
    qs_decision: str | None
    qs_comments: str | None
    qs_decided_at: datetime | None
    engineer_decision: str | None
    engineer_comments: str | None
    engineer_decided_at: datetime | None
