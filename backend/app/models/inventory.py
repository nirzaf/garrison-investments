from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class StorageLocation(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "storage_locations"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    location_type: Mapped[str] = mapped_column(String(30), nullable=False)
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class InventoryItem(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "inventory_items"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    minimum_stock: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    reorder_level: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    supplier_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))


class InventoryLocationStock(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "inventory_location_stock"
    __table_args__ = (
        CheckConstraint("on_hand_qty >= 0", name="on_hand_nonnegative"),
        CheckConstraint("reserved_qty >= 0", name="reserved_nonnegative"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    location_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    on_hand_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    reserved_qty: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )

    item: Mapped[InventoryItem] = relationship(lazy="selectin")
    location: Mapped[StorageLocation] = relationship(lazy="selectin")


class InventoryAsset(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "inventory_assets"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_tag: Mapped[str] = mapped_column(String(80), nullable=False)
    current_location_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    condition: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("'good'")
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'active'"))

    item: Mapped[InventoryItem] = relationship(lazy="selectin")
    current_location: Mapped[StorageLocation] = relationship(lazy="selectin")


class MaterialRequest(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "material_requests"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    request_number: Mapped[str] = mapped_column(String(60), nullable=False)
    project_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    requester_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    from_location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default=text("'requested'")
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    submission_revision: Mapped[int | None] = mapped_column(Integer)
    previous_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("material_requests.id", ondelete="RESTRICT")
    )
    draft_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    correction_target_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "material_requests.id", name="fk_material_requests_draft_target", ondelete="RESTRICT"
        )
    )
    correction_expected_revision: Mapped[int | None] = mapped_column(Integer)
    total_estimated_cost: Mapped[Decimal] = mapped_column(
        Numeric(14, 2),
        nullable=False,
        server_default=text("0"),
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    lines: Mapped[list["MaterialRequestLine"]] = relationship(
        back_populates="request",
        cascade="all, delete-orphan",
        lazy="selectin",
        primaryjoin="and_(MaterialRequest.id == MaterialRequestLine.request_id, "
        "MaterialRequestLine.deleted_at.is_(None))",
    )


class MaterialRequestSubmission(TimestampMixin, Base):
    __tablename__ = "material_request_submissions"

    request_id: Mapped[UUID] = mapped_column(
        ForeignKey("material_requests.id", ondelete="RESTRICT"), primary_key=True
    )
    submission_revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    engineer_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    manager_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    processor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)


class InventoryRegistration(TimestampMixin, Base):
    __tablename__ = "inventory_registrations"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"))
    location_id: Mapped[UUID] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="RESTRICT")
    )
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    root_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_registrations.id", ondelete="RESTRICT")
    )
    previous_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_registrations.id", ondelete="RESTRICT"), unique=True
    )
    submission_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'draft'"))
    requirements: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_comments: Mapped[str | None] = mapped_column(Text)
    confirmed_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT")
    )
    movement_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_movements.id", ondelete="RESTRICT"), unique=True
    )


class MaterialRequestLine(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "material_request_lines"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    request_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("material_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    issued_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3),
        nullable=False,
        server_default=text("0"),
    )
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    request: Mapped[MaterialRequest] = relationship(back_populates="lines")
    item: Mapped[InventoryItem] = relationship(lazy="selectin")


class InventoryMovement(TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "inventory_movements"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("uuid_generate_v4()"),
    )
    item_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("inventory_assets.id", ondelete="SET NULL"),
        nullable=True,
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    from_location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_location_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("storage_locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    project_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reference_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    registration_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("inventory_registrations.id", ondelete="RESTRICT"), unique=True
    )
    handled_by: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Import provenance: a redelivered batch must recognise the rows it already applied.
    import_batch_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), nullable=True)
    import_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)

    item: Mapped[InventoryItem] = relationship(lazy="selectin")
