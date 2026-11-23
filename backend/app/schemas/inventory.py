from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.approvals import ApprovalResponse


class LocationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    code: str = Field(min_length=2, max_length=40)
    location_type: str = Field(pattern="^(warehouse|site_store|project_site)$")
    project_id: UUID | None = None
    address: str | None = None


class LocationResponse(LocationCreateRequest):
    id: UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class InventoryItemCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    item_code: str | None = Field(default=None, max_length=60)
    category: str = Field(min_length=2, max_length=80)
    item_type: str = Field(pattern="^(consumable|asset)$")
    unit: str = Field(pattern="^(Nos|KG|TON|SQM|bag|m|m2)$")
    minimum_stock: Decimal = Decimal("0")
    reorder_level: Decimal = Decimal("0")
    unit_cost: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    supplier_id: UUID


class InventoryItemResponse(BaseModel):
    id: UUID
    name: str
    item_code: str | None
    category: str
    item_type: str
    unit: str
    minimum_stock: Decimal
    reorder_level: Decimal
    unit_cost: Decimal | None
    supplier_id: UUID | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class StockResponse(BaseModel):
    id: UUID
    item_id: UUID
    location_id: UUID
    location_name: str
    on_hand_qty: Decimal
    reserved_qty: Decimal
    available_qty: Decimal


class AssetCreateRequest(BaseModel):
    item_id: UUID
    asset_tag: str = Field(min_length=2, max_length=80)
    current_location_id: UUID
    condition: str = Field(default="good", max_length=40)


class AssetResponse(BaseModel):
    id: UUID
    item_id: UUID
    asset_tag: str
    current_location_id: UUID
    condition: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class MovementCreateRequest(BaseModel):
    item_id: UUID
    asset_id: UUID | None = None
    movement_type: str = Field(
        pattern="^(receive|reserve|issue|transfer|return|consume|adjustment|wastage|damaged)$"
    )
    quantity: Decimal = Field(
        max_digits=14,
        decimal_places=3,
        description="Positive, or negative for a stock adjustment. Up to three decimal places.",
    )
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    project_id: UUID | None = None
    reference_type: str | None = None
    reference_id: UUID | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_quantity(self) -> Self:
        if self.quantity == 0 or (self.quantity < 0 and self.movement_type != "adjustment"):
            raise ValueError("Use a positive quantity or a negative quantity for an adjustment.")
        return self


class MovementResponse(BaseModel):
    id: UUID
    item_id: UUID
    asset_id: UUID | None
    movement_type: str
    quantity: Decimal
    from_location_id: UUID | None
    to_location_id: UUID | None
    project_id: UUID | None
    reference_type: str | None
    reference_id: UUID | None
    handled_by: UUID | None
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaterialRequestLineCreate(BaseModel):
    item_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class MaterialRequestCreateRequest(BaseModel):
    project_id: UUID
    from_location_id: UUID
    notes: str | None = None
    lines: list[MaterialRequestLineCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_items(self) -> Self:
        if len({line.item_id for line in self.lines}) != len(self.lines):
            raise ValueError("Select each inventory item only once.")
        return self


class MaterialSubmissionRequirements(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    required_date: date
    urgency: Literal["routine", "urgent", "critical"]
    purpose: str = Field(min_length=1, max_length=2000)
    specification: str = Field(min_length=1, max_length=2000)
    stock_availability: str | None = Field(default=None, max_length=1000)
    supporting_document_ids: list[UUID] = Field(default_factory=list, max_length=10)


class MaterialRequestSubmitRequest(MaterialRequestCreateRequest):
    requirements: MaterialSubmissionRequirements


class MaterialRequestResubmitRequest(MaterialRequestSubmitRequest):
    expected_revision: int = Field(ge=1)


class MaterialSubmissionLine(MaterialRequestLineCreate):
    name: str
    unit: str


class MaterialSubmissionSnapshot(BaseModel):
    project_id: UUID
    from_location_id: UUID
    requirements: MaterialSubmissionRequirements
    notes: str | None
    lines: list[MaterialSubmissionLine]
    evidence_versions: dict[str, int]


class MaterialSubmissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_revision: int
    submitted_by: UUID
    engineer_id: UUID
    manager_id: UUID
    processor_id: UUID | None
    requirements: MaterialSubmissionSnapshot
    created_at: datetime


class MaterialSubmissionHistoryResponse(BaseModel):
    submissions: list[MaterialSubmissionResponse]
    decisions: list[ApprovalResponse]


class RequestProjectOption(BaseModel):
    id: UUID
    code: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class RequestProjectOptions(BaseModel):
    items: list[RequestProjectOption]
    total: int


class MaterialRequestLineResponse(BaseModel):
    id: UUID
    item_id: UUID
    quantity: Decimal
    reserved_quantity: Decimal
    issued_quantity: Decimal
    unit_cost: Decimal | None

    model_config = ConfigDict(from_attributes=True)


class MaterialRequestResponse(BaseModel):
    id: UUID
    request_number: str
    project_id: UUID
    requester_id: UUID | None
    from_location_id: UUID | None
    status: str
    revision: int
    submission_revision: int | None = None
    total_estimated_cost: Decimal | None
    notes: str | None
    lines: list[MaterialRequestLineResponse]

    model_config = ConfigDict(from_attributes=True)


class MaterialQuantityLine(BaseModel):
    line_id: UUID
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)


class MaterialQuantityCommand(BaseModel):
    expected_revision: int = Field(ge=1)
    lines: list[MaterialQuantityLine] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def distinct_lines(self) -> Self:
        if len({line.line_id for line in self.lines}) != len(self.lines):
            raise ValueError("Select each request line only once.")
        return self


class InventoryRegistrationCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    location_id: UUID
    name: str = Field(min_length=2, max_length=180)
    description: str = Field(min_length=1, max_length=2000)
    category: Literal["material", "tool", "equipment"]
    unit: Literal["Nos", "KG", "TON", "SQM", "bag", "m", "m2"]
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=3)
    condition: Literal["new", "used"]
    received_date: date
    supplier_id: UUID | None = None
    source: str | None = Field(default=None, max_length=160)
    brand: str | None = Field(default=None, max_length=100)
    model_number: str | None = Field(default=None, max_length=100)
    serial_number: str | None = Field(default=None, max_length=80)
    catalog_item_id: UUID | None = None
    remarks: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def discrete_assets(self) -> Self:
        if self.category == "material":
            return self
        if self.unit != "Nos" or self.quantity != int(self.quantity) or self.quantity > 100:
            raise ValueError("Register up to 100 whole tools or equipment units at a time.")
        if self.serial_number and self.quantity != 1:
            raise ValueError("Register serial-numbered tools and equipment individually.")
        return self


class InventoryRegistrationSubmitRequest(BaseModel):
    expected_submission_revision: int = Field(ge=1)


class InventoryRegistrationDecisionRequest(InventoryRegistrationSubmitRequest):
    decision: Literal["approved", "rejected", "returned"]
    comments: str | None = Field(default=None, max_length=2000)


class InventoryRegistrationCorrectionRequest(InventoryRegistrationCreateRequest):
    expected_submission_revision: int = Field(ge=1)


class InventoryRegistrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    location_id: UUID
    created_by: UUID
    root_id: UUID | None
    previous_id: UUID | None
    submission_revision: int
    requirements: InventoryRegistrationCreateRequest
    status: str
    evidence_ids: list[UUID]
    reviewer_id: UUID | None
    submitted_at: datetime | None
    decided_at: datetime | None
    decision_comments: str | None
    confirmed_item_id: UUID | None
    movement_id: UUID | None


class InventoryRegistrationPageResponse(BaseModel):
    items: list[InventoryRegistrationResponse]
    total: int
