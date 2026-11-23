"""Store user feedback and bounded request diagnostics."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310099"
down_revision = "202605310098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_feedback",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("reporter_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("submission_fingerprint", sa.String(64), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("title", sa.String(140), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="new"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("diagnostics", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("reporter_id", "submission_id"),
        sa.CheckConstraint("category IN ('bug', 'suggestion', 'other')", name="category"),
        sa.CheckConstraint("status IN ('new', 'investigating', 'resolved')", name="status"),
        sa.CheckConstraint("revision >= 1", name="revision"),
        sa.Index("ix_user_feedback_reporter_created", "reporter_id", "created_at"),
        sa.Index("ix_user_feedback_created", "created_at", "id"),
    )


def downgrade() -> None:
    op.drop_table("user_feedback")
