"""Retain the exact approved evidence used for a training completion."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310033"
down_revision: str | None = "202605310032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hr_training_completions",
        sa.Column(
            "enrollment_id",
            sa.Uuid(),
            sa.ForeignKey("hr_training_enrollments.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "certificate_id",
            sa.Uuid(),
            sa.ForeignKey("hr_certifications.id", ondelete="RESTRICT"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            sa.Uuid(),
            sa.ForeignKey("hr_document_versions.id", ondelete="RESTRICT"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "verified_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_training_completions)")):
        raise RuntimeError("Cannot remove retained training completion evidence.")
    op.drop_table("hr_training_completions")
