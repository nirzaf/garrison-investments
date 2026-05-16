from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class InvoiceCreateRequest(BaseModel):
    invoice_number: str = Field(min_length=2, max_length=80)
    project_id: UUID
    supplier_id: UUID | None = None
    invoice_date: date
    due_date: date
    amount: Decimal = Field(gt=0)
    tax_amount: Decimal = Decimal("0")
    attachment_key: str | None = Field(default=None, max_length=500)
    notes: str | None = None


class InvoiceUpdateRequest(BaseModel):
    status: str | None = Field(default=None, pattern="^(draft|submitted|approved|rejected)$")
    notes: str | None = None


class PaymentCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(gt=0)
    method: str = Field(min_length=2, max_length=50)
    reference_number: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class PaymentResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    payment_date: date
    amount: Decimal
    method: str
    reference_number: str | None
    recorded_by: UUID | None
    notes: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvoiceResponse(BaseModel):
    id: UUID
    invoice_number: str
    project_id: UUID
    supplier_id: UUID | None
    invoice_date: date
    due_date: date
    amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    status: str
    payment_status: str
    attachment_key: str | None
    created_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    notes: str | None
    payments: list[PaymentResponse]

    model_config = ConfigDict(from_attributes=True)


class InvoiceListResponse(BaseModel):
    items: list[InvoiceResponse]
    total: int


class BudgetSummaryResponse(BaseModel):
    project_id: UUID
    budget_amount: Decimal
    invoiced_total: Decimal
    paid_total: Decimal
    remaining_budget: Decimal


class InvoiceAttachmentUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
