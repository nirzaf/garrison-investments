from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    unit_cost: Decimal | None = None
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
    quantity: Decimal = Field(gt=0)
    from_location_id: UUID | None = None
    to_location_id: UUID | None = None
    project_id: UUID | None = None
    reference_type: str | None = None
    reference_id: UUID | None = None
    notes: str | None = None


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
    quantity: Decimal = Field(gt=0)


class MaterialRequestCreateRequest(BaseModel):
    project_id: UUID
    from_location_id: UUID
    notes: str | None = None
    lines: list[MaterialRequestLineCreate] = Field(min_length=1)


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
    total_estimated_cost: Decimal
    notes: str | None
    lines: list[MaterialRequestLineResponse]

    model_config = ConfigDict(from_attributes=True)
