"""Add fail-closed classification to documents and uploaded media."""

import sqlalchemy as sa

from alembic import op

revision = "202605310110"
down_revision = "202605310109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("documents", "photos"):
        op.add_column(
            table,
            sa.Column(
                "classification",
                sa.String(length=20),
                server_default=sa.text("'unclassified'"),
                nullable=False,
            ),
        )

    # Preserve the pre-existing financial-document restriction in an explicit
    # classification so the new policy does not infer broad access for these rows.
    op.execute(
        "UPDATE documents SET classification = 'financial' "
        "WHERE lower(document_type) IN ('contract', 'invoice')"
    )


def downgrade() -> None:
    connection = op.get_bind()
    classified_records = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM documents WHERE classification <> 'unclassified') "
            "OR EXISTS (SELECT 1 FROM photos WHERE classification <> 'unclassified')"
        )
    )
    if classified_records:
        raise RuntimeError(
            "Cannot remove evidence classification after review decisions have been recorded."
        )
    op.drop_column("photos", "classification")
    op.drop_column("documents", "classification")
