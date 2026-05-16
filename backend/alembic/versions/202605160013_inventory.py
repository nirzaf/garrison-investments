"""add inventory, movements, and material requests

Revision ID: 202605160013
Revises: 202605160012
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160013"
down_revision: str | None = "202605160012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("location_type", sa.String(length=30), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("uq_storage_locations_code_active", "storage_locations", ["code"], unique=True)
    op.create_index("idx_storage_locations_type", "storage_locations", ["location_type"])

    op.create_table(
        "inventory_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("item_code", sa.String(length=60), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("item_type", sa.String(length=30), nullable=False),
        sa.Column("unit", sa.String(length=20), nullable=False),
        sa.Column("minimum_stock", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("reorder_level", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_inventory_items_code_active",
        "inventory_items",
        ["item_code"],
        unique=True,
        postgresql_where=sa.text("item_code IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index("idx_inventory_items_category", "inventory_items", ["category"])
    op.create_index("idx_inventory_items_type", "inventory_items", ["item_type"])

    op.create_table(
        "inventory_location_stock",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("on_hand_qty", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column("reserved_qty", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("item_id", "location_id", name="uq_inventory_stock_item_location"),
    )
    op.create_index("idx_inventory_stock_item", "inventory_location_stock", ["item_id"])
    op.create_index("idx_inventory_stock_location", "inventory_location_stock", ["location_id"])

    op.create_table(
        "inventory_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_tag", sa.String(length=80), nullable=False),
        sa.Column(
            "current_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "condition", sa.String(length=40), nullable=False, server_default=sa.text("'good'")
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'active'")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_inventory_assets_tag_active", "inventory_assets", ["asset_tag"], unique=True
    )
    op.create_index("idx_assets_current_location", "inventory_assets", ["current_location_id"])

    op.create_table(
        "material_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("request_number", sa.String(length=60), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "from_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'requested'")
        ),
        sa.Column(
            "total_estimated_cost", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_material_requests_number", "material_requests", ["request_number"], unique=True
    )
    op.create_index("idx_material_requests_project", "material_requests", ["project_id", "status"])

    op.create_table(
        "material_request_lines",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "reserved_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "issued_quantity", sa.Numeric(14, 3), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "inventory_movements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("inventory_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column(
            "from_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("storage_locations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reference_type", sa.String(length=40), nullable=True),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "handled_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_inventory_movements_item", "inventory_movements", ["item_id", "created_at"]
    )
    op.create_index("idx_inventory_movements_asset", "inventory_movements", ["asset_id"])
    op.create_index("idx_inventory_movements_project", "inventory_movements", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_inventory_movements_project", table_name="inventory_movements")
    op.drop_index("idx_inventory_movements_asset", table_name="inventory_movements")
    op.drop_index("idx_inventory_movements_item", table_name="inventory_movements")
    op.drop_table("inventory_movements")
    op.drop_table("material_request_lines")
    op.drop_index("idx_material_requests_project", table_name="material_requests")
    op.drop_index("uq_material_requests_number", table_name="material_requests")
    op.drop_table("material_requests")
    op.drop_index("idx_assets_current_location", table_name="inventory_assets")
    op.drop_index("uq_inventory_assets_tag_active", table_name="inventory_assets")
    op.drop_table("inventory_assets")
    op.drop_index("idx_inventory_stock_location", table_name="inventory_location_stock")
    op.drop_index("idx_inventory_stock_item", table_name="inventory_location_stock")
    op.drop_table("inventory_location_stock")
    op.drop_index("idx_inventory_items_type", table_name="inventory_items")
    op.drop_index("idx_inventory_items_category", table_name="inventory_items")
    op.drop_index("uq_inventory_items_code_active", table_name="inventory_items")
    op.drop_table("inventory_items")
    op.drop_index("idx_storage_locations_type", table_name="storage_locations")
    op.drop_index("uq_storage_locations_code_active", table_name="storage_locations")
    op.drop_table("storage_locations")
