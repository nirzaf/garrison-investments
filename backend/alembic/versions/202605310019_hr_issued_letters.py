"""Retain private HR letter drafts and independent issuance decisions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310019"
down_revision: str | None = "202605310018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_issued_letters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("hr_letter_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("employee_revision", sa.Integer(), nullable=False),
        sa.Column("content_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column(
            "prepared_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("reason_encrypted", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND decided_by IS NULL AND decided_at IS NULL "
            "AND reason_encrypted IS NULL) OR "
            "(status IN ('issued', 'rejected') AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by <> prepared_by "
            "AND ((status = 'rejected') = (reason_encrypted IS NOT NULL)))",
            name="hr_letter_decision",
        ),
    )
    # The table is new and empty in this transaction.
    op.create_index(
        "ix_hr_issued_letters_employee_created",
        "hr_issued_letters",
        ["employee_id", "created_at", "id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_issued_letters)")):
        raise RuntimeError("Cannot remove retained HR letters.")
    op.drop_table("hr_issued_letters")
