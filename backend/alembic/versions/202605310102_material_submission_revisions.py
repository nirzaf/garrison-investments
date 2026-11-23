"""Separate immutable material submissions from stock concurrency revisions."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605310102"
down_revision = "202605310101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("material_requests", sa.Column("submission_revision", sa.Integer()))
    op.create_table(
        "material_request_submissions",
        sa.Column(
            "request_id",
            sa.Uuid(),
            sa.ForeignKey("material_requests.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("submission_revision", sa.Integer(), primary_key=True),
        *[
            sa.Column(
                column,
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="RESTRICT"),
                nullable=column == "processor_id",
            )
            for column in ("submitted_by", "engineer_id", "manager_id", "processor_id")
        ],
        sa.Column("requirements", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("submission_revision >= 1", name="positive_submission_revision"),
    )
    op.add_column("approvals", sa.Column("submission_revision", sa.Integer()))
    op.add_column("approvals", sa.Column("decided_by", sa.Uuid()))
    op.create_foreign_key(
        "fk_approvals_decided_by", "approvals", "users", ["decided_by"], ["id"], ondelete="RESTRICT"
    )
    op.create_foreign_key(
        "fk_approvals_material_submission",
        "approvals",
        "material_request_submissions",
        ["request_id", "submission_revision"],
        ["request_id", "submission_revision"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "material_submission_stage",
        "approvals",
        "submission_revision IS NULL OR "
        "(request_type = 'material_request' AND step_order IN (1, 2))",
    )
    op.create_index(
        "uq_approvals_material_submission_stage",
        "approvals",
        ["request_id", "submission_revision", "step_order"],
        unique=True,
        postgresql_where=sa.text("submission_revision IS NOT NULL"),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve material submissions and their approval decisions on rollback.")
