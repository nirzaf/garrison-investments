from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class BoqItem(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "boq_items"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    project_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    milestone_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("project_milestones.id", ondelete="SET NULL"),
        nullable=True,
    )
    item_code: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    phase: Mapped[str | None] = mapped_column(String(100), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    approved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    unit_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    planned_amount: Mapped[Decimal] = mapped_column(Numeric(15, 2), nullable=False)
