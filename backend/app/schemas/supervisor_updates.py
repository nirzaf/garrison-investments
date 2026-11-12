from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class SupervisorUpdateSubmitRequest(BaseModel):
    notes: str | None = None


class SupervisorUpdateResponse(BaseModel):
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
    verified_report_id: UUID | None
    verified_by_name: str | None = None
    verification_notes: str | None

    model_config = ConfigDict(from_attributes=True)


class SupervisorUpdateListResponse(BaseModel):
    items: list[SupervisorUpdateResponse]
    total: int
