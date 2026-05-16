from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReportManpowerInput(BaseModel):
    trade: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=0)
    overtime_hours: Decimal = Field(default=Decimal("0"), ge=0)


class ReportEquipmentInput(BaseModel):
    equipment_name: str = Field(min_length=1, max_length=120)
    quantity: int = Field(ge=0)
    hours_used: Decimal = Field(default=Decimal("0"), ge=0)
    remarks: str | None = None


class ReportMaterialConsumptionInput(BaseModel):
    boq_item_id: UUID | None = None
    material_name: str = Field(min_length=1, max_length=160)
    unit: str = Field(min_length=1, max_length=30)
    quantity: Decimal = Field(gt=0)
    remarks: str | None = None


class ReportFileRef(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="file", max_length=30)


class DailyReportCreateRequest(BaseModel):
    project_id: UUID
    report_date: date
    work_location: str = Field(min_length=1, max_length=255)
    manpower_total: int = Field(ge=0)
    overtime_hours: Decimal = Field(default=Decimal("0"), ge=0)
    work_completed: str = Field(min_length=1)
    progress_percentage: Decimal = Field(ge=0, le=100)
    safety_incidents: int = Field(default=0, ge=0)
    safety_notes: str | None = None
    wir_status: str = Field(min_length=1, max_length=50)
    inspection_status: str = Field(min_length=1, max_length=50)
    delay_notes: str | None = None
    next_day_plan: str = Field(min_length=1)
    supervisor_update_ids: list[UUID] = Field(default_factory=list)
    photo_refs: list[ReportFileRef] = Field(default_factory=list)
    attachment_refs: list[ReportFileRef] = Field(default_factory=list)
    manpower_entries: list[ReportManpowerInput] = Field(default_factory=list)
    equipment_entries: list[ReportEquipmentInput] = Field(default_factory=list)
    material_consumption: list[ReportMaterialConsumptionInput] = Field(default_factory=list)
    extra_fields: dict[str, Any] = Field(default_factory=dict)


class DailyReportUpdateRequest(DailyReportCreateRequest):
    pass


class ReportManpowerResponse(ReportManpowerInput):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class ReportEquipmentResponse(ReportEquipmentInput):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class ReportMaterialConsumptionResponse(ReportMaterialConsumptionInput):
    id: UUID
    model_config = ConfigDict(from_attributes=True)


class DailyReportApprovalHistoryResponse(BaseModel):
    id: UUID
    actor_id: UUID | None
    decision: str
    previous_status: str
    comments: str | None
    decided_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DailyReportDecisionRequest(BaseModel):
    comments: str | None = None


class DailyReportResponse(BaseModel):
    id: UUID
    project_id: UUID
    engineer_id: UUID
    report_number: str | None
    report_date: date
    work_location: str
    manpower_total: int
    overtime_hours: Decimal
    work_completed: str
    progress_percentage: Decimal
    safety_incidents: int
    safety_notes: str | None
    wir_status: str
    inspection_status: str
    delay_notes: str | None
    next_day_plan: str
    supervisor_update_ids: list[str]
    photo_refs: list[dict[str, Any]]
    attachment_refs: list[dict[str, Any]]
    status: str
    submitted_at: datetime | None
    approved_by: UUID | None
    approved_at: datetime | None
    rejection_comments: str | None
    extra_fields: dict[str, Any]
    manpower_entries: list[ReportManpowerResponse]
    equipment_entries: list[ReportEquipmentResponse]
    material_consumption: list[ReportMaterialConsumptionResponse]
    approval_history: list[DailyReportApprovalHistoryResponse]

    model_config = ConfigDict(from_attributes=True)


class DailyReportListResponse(BaseModel):
    items: list[DailyReportResponse]
    total: int
