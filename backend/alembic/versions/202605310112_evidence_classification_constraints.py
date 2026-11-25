"""Constrain persisted evidence classifications and version snapshots."""

import sqlalchemy as sa

from alembic import op

revision = "202605310112"
down_revision = "202605310111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column(
            "classification",
            sa.String(length=20),
            server_default=sa.text("'unclassified'"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE document_versions AS version "
        "SET classification = document.classification "
        "FROM documents AS document "
        "WHERE document.id = version.document_id"
    )
    for table in ("documents", "document_versions", "photos"):
        op.create_check_constraint(
            f"ck_{table}_classification",
            table,
            "classification IN ('unclassified', 'operational', 'financial')",
        )
    # Match Python's canonical-type check, including whitespace and casing.
    op.execute(
        "UPDATE documents SET classification = 'financial' "
        "WHERE lower(btrim(document_type)) IN ('contract', 'invoice')"
    )
    op.execute(
        "UPDATE document_versions AS version SET classification = 'financial' "
        "FROM documents AS document WHERE document.id = version.document_id "
        "AND lower(btrim(document.document_type)) IN ('contract', 'invoice')"
    )


def downgrade() -> None:
    connection = op.get_bind()
    reviewed = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_versions WHERE classification <> 'unclassified')"
        )
    )
    if reviewed:
        raise RuntimeError(
            "Cannot remove document-version classification after evidence has been reviewed."
        )
    for table in ("documents", "document_versions", "photos"):
        op.drop_constraint(f"ck_{table}_classification", table, type_="check")
    op.drop_column("document_versions", "classification")
