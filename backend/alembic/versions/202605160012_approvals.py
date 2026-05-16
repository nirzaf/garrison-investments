"""add generic approvals

Revision ID: 202605160012
Revises: 202605160011
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160012"
down_revision: str | None = "202605160011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("request_type", sa.String(length=60), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "submitter_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approver_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "delegated_to_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "escalation_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status", sa.String(length=30), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("submitter_comments", sa.Text(), nullable=True),
        sa.Column("decision_comments", sa.Text(), nullable=True),
        sa.Column("delegation_reason", sa.Text(), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_approvals_request", "approvals", ["request_type", "request_id"])
    op.create_index("idx_approvals_inbox", "approvals", ["approver_id", "status"])
    op.create_index("idx_approvals_delegate_inbox", "approvals", ["delegated_to_id", "status"])
    op.create_index("idx_approvals_outbox", "approvals", ["submitter_id", "status"])
    op.create_index("idx_approvals_due", "approvals", ["status", "due_at"])


def downgrade() -> None:
    op.drop_index("idx_approvals_due", table_name="approvals")
    op.drop_index("idx_approvals_outbox", table_name="approvals")
    op.drop_index("idx_approvals_delegate_inbox", table_name="approvals")
    op.drop_index("idx_approvals_inbox", table_name="approvals")
    op.drop_index("idx_approvals_request", table_name="approvals")
    op.drop_table("approvals")
