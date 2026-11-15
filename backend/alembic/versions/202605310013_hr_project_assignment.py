"""Record HR project-assignment requests and decisions.

Revision ID: 202605310013
Revises: 202605310012
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310013"
down_revision: str | None = "202605310012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "hr_project_assignment_requests"
    op.create_table(
        table,
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "employee_id",
            sa.Uuid(),
            sa.ForeignKey("hr_employees.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("linked_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("requested_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("role_in_project", sa.String(50)),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("action IN ('assign', 'revoke')", name="hr_assignment_action"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="hr_assignment_status"
        ),
    )
    # The new table is empty and the indexes become visible atomically with it.
    op.create_index("ix_hr_project_assignment_requests_employee_id", table, ["employee_id"])
    op.create_index("ix_hr_project_assignment_requests_project_id", table, ["project_id"])
    op.create_index(
        "uq_hr_project_assignment_pending",
        table,
        ["project_id", "employee_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("hr_project_assignment_requests")
