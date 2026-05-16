"""add suppliers

Revision ID: 202605160014
Revises: 202605160013
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160014"
down_revision: str | None = "202605160013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("rating", sa.String(length=20), nullable=False),
        sa.Column("payment_terms", sa.String(length=120), nullable=False),
        sa.Column("contact_person", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("tax_registration_number", sa.String(length=80), nullable=False),
        sa.Column("tds_certificate_number", sa.String(length=120), nullable=True),
        sa.Column("tds_expiry_date", sa.Date(), nullable=True),
        sa.Column("tds_document_key", sa.String(length=500), nullable=True),
        sa.Column("compliance_status", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_suppliers_active", "suppliers", ["is_active", "name"])
    op.create_index("idx_suppliers_compliance", "suppliers", ["compliance_status"])
    op.create_foreign_key(
        "fk_inventory_items_supplier_id_suppliers",
        "inventory_items",
        "suppliers",
        ["supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_inventory_items_supplier_id_suppliers",
        "inventory_items",
        type_="foreignkey",
    )
    op.drop_index("idx_suppliers_compliance", table_name="suppliers")
    op.drop_index("idx_suppliers_active", table_name="suppliers")
    op.drop_table("suppliers")
