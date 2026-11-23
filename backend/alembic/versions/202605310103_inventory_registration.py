"""Store project inventory registrations independently of confirmed stock."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310103"
down_revision = "202605310102"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_registrations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuid_generate_v4()"), primary_key=True),
        sa.Column("submission_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("requirements", JSONB(), nullable=False),
        sa.Column("evidence_ids", JSONB(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_comments", sa.Text()),
        *[
            sa.Column(
                column,
                sa.Uuid(),
                sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"),
                nullable=nullable,
            )
            for column, table, nullable in (
                ("project_id", "projects", False),
                ("location_id", "storage_locations", False),
                ("created_by", "users", False),
                ("root_id", "inventory_registrations", True),
                ("previous_id", "inventory_registrations", True),
                ("reviewer_id", "users", True),
                ("confirmed_item_id", "inventory_items", True),
                ("movement_id", "inventory_movements", True),
            )
        ],
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("previous_id"),
        sa.UniqueConstraint("movement_id"),
        sa.CheckConstraint(
            "status IN ('draft','pending_engineer','returned','rejected','approved')",
            name="inventory_registration_status",
        ),
        sa.CheckConstraint(
            "(previous_id IS NULL AND root_id IS NULL AND submission_revision = 1) OR "
            "(previous_id IS NOT NULL AND root_id IS NOT NULL AND submission_revision > 1)",
            name="inventory_registration_revision",
        ),
    )
    op.create_index(
        "ix_inventory_registrations_scope",
        "inventory_registrations",
        ["project_id", "created_at", "id"],
    )
    op.create_index("ix_inventory_registrations_root", "inventory_registrations", ["root_id"])
    op.add_column(
        "inventory_movements",
        sa.Column("registration_id", sa.Uuid()),
    )
    op.create_foreign_key(
        "fk_inventory_movements_registration_id_inventory_registrations",
        "inventory_movements",
        "inventory_registrations",
        ["registration_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_inventory_movements_registration_id", "inventory_movements", ["registration_id"]
    )


def downgrade() -> None:
    raise RuntimeError("Preserve registration history and receipts on application rollback.")
