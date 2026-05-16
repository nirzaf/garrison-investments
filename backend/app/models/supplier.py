from datetime import date
from uuid import UUID

from sqlalchemy import Boolean, Date, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Supplier(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    payment_terms: Mapped[str] = mapped_column(String(120), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    tax_registration_number: Mapped[str] = mapped_column(String(80), nullable=False)
    tds_certificate_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tds_expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tds_document_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    compliance_status: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
