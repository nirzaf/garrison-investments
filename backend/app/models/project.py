from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Project(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_of_work: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        server_default=text("'planning'"),
    )
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    progress_percentage: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        server_default=text("0"),
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
