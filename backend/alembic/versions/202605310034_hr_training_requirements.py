"""Store mandatory training scope by HR position and project site."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310034"
down_revision: str | None = "202605310033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_training_requirements",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "course_id",
            sa.Uuid(),
            sa.ForeignKey("hr_training_courses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position_id", sa.Uuid(), sa.ForeignKey("hr_positions.id", ondelete="RESTRICT")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="RESTRICT")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "position_id IS NOT NULL OR project_id IS NOT NULL", name="training_rule_scope"
        ),
        sa.UniqueConstraint(
            "course_id", "position_id", "project_id", postgresql_nulls_not_distinct=True
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_training_requirements)")):
        raise RuntimeError("Cannot remove recorded training requirements.")
    op.drop_table("hr_training_requirements")
