from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SupplierCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=80)
    rating: str = Field(min_length=1, max_length=20)
    payment_terms: str = Field(min_length=2, max_length=120)
    contact_person: str = Field(min_length=2, max_length=150)
    phone: str = Field(min_length=3, max_length=32)
    email: EmailStr
    address: str = Field(min_length=3)
    tax_registration_number: str = Field(min_length=2, max_length=80)
    tds_certificate_number: str | None = Field(default=None, max_length=120)
    tds_expiry_date: date | None = None
    compliance_status: str = Field(pattern="^(compliant|pending|expired|blocked)$")


class SupplierUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    rating: str | None = Field(default=None, min_length=1, max_length=20)
    payment_terms: str | None = Field(default=None, min_length=2, max_length=120)
    contact_person: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, min_length=3, max_length=32)
    email: EmailStr | None = None
    address: str | None = Field(default=None, min_length=3)
    tax_registration_number: str | None = Field(default=None, min_length=2, max_length=80)
    tds_certificate_number: str | None = Field(default=None, max_length=120)
    tds_expiry_date: date | None = None
    compliance_status: str | None = Field(
        default=None, pattern="^(compliant|pending|expired|blocked)$"
    )
    is_active: bool | None = None


class SupplierResponse(BaseModel):
    id: UUID
    name: str
    category: str
    rating: str
    payment_terms: str
    contact_person: str
    phone: str
    email: str
    address: str
    tax_registration_number: str
    tds_certificate_number: str | None
    tds_expiry_date: date | None
    tds_document_key: str | None
    compliance_status: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class SupplierListResponse(BaseModel):
    items: list[SupplierResponse]
    total: int
