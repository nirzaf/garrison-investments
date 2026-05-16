"""add documents

Revision ID: 202605160010
Revises: 202605160009
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605160010"
down_revision: str | None = "202605160009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending_approval'"),
        ),
        sa.Column("active_version", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'active', 'superseded', 'archived')",
            name="ck_documents_status_valid",
        ),
    )
    op.create_index(
        "idx_documents_project",
        "documents",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_documents_type",
        "documents",
        ["document_type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("idx_documents_status", "documents", ["status"])
    op.create_index(
        "idx_documents_search",
        "documents",
        [sa.text("to_tsvector('english', title)")],
        postgresql_using="gin",
    )

    op.create_table(
        "document_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'pending_approval'"),
        ),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=80), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "approved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_comments", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.CheckConstraint(
            "status IN ('pending_approval', 'active', 'superseded', 'rejected')",
            name="ck_document_versions_status_valid",
        ),
    )
    op.create_index(
        "idx_document_versions_document",
        "document_versions",
        ["document_id", "version"],
        unique=True,
    )
    op.create_index("idx_document_versions_status", "document_versions", ["status"])


def downgrade() -> None:
    op.drop_index("idx_document_versions_status", table_name="document_versions")
    op.drop_index("idx_document_versions_document", table_name="document_versions")
    op.drop_table("document_versions")
    op.drop_index("idx_documents_search", table_name="documents")
    op.drop_index("idx_documents_status", table_name="documents")
    op.drop_index("idx_documents_type", table_name="documents")
    op.drop_index("idx_documents_project", table_name="documents")
    op.drop_table("documents")
