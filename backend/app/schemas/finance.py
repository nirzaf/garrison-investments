from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.business_policy import BusinessCurrency

InvoiceAction = Literal["correct", "resubmit", "approve", "reject", "record_payment"]


class ApprovalCurrencyCount(BaseModel):
    request_type: str
    currency: str | None
    count: int


class CurrencyReconciliationResponse(BaseModel):
    business_currency: BusinessCurrency
    unlabelled_row_counts: dict[str, int]
    approval_currency_counts: list[ApprovalCurrencyCount]


class InvoiceCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_number: str = Field(min_length=2, max_length=80)
    project_id: UUID
    supplier_id: UUID | None = None
    invoice_date: date
    due_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    notes: str | None = None


class InvoiceUpdateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    expected_revision: int | None = Field(default=None, ge=1)
    status: str | None = Field(default=None, pattern="^(draft|submitted|approved|rejected)$")
    notes: str | None = None
    invoice_number: str | None = Field(default=None, min_length=2, max_length=80)
    supplier_id: UUID | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=14, decimal_places=2)
    tax_amount: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)

    @field_validator(
        "invoice_number", "invoice_date", "due_date", "amount", "tax_amount", mode="before"
    )
    @classmethod
    def require_non_null_field(cls, value: object) -> object:
        if value is None:
            raise ValueError("This field cannot be cleared.")
        return value


class PaymentCreateRequest(BaseModel):
    payment_date: date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
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
    supplier_name: str | None = None
    project_name: str | None = None
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
    revision: int
    payments: list[PaymentResponse]
    allowed_actions: list[InvoiceAction] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def paid_total(self) -> Decimal:
        return sum((payment.amount for payment in self.payments), Decimal("0.00"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.paid_total


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


class InvoiceSupplierOption(BaseModel):
    id: UUID
    name: str


class InvoiceSupplierOptionsResponse(BaseModel):
    items: list[InvoiceSupplierOption]
    total: int
