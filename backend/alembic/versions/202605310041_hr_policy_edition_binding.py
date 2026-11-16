"""Keep the exact document revision and predecessor of each published policy."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310041"
down_revision: str | None = "202605310040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hr_policy_documents"
CHECK = "ck_hr_policy_documents_hr_policy_version_requires_document"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("document_version_number", sa.Integer()))
    op.add_column(TABLE, sa.Column("supersedes_policy_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_hr_policy_exact_version",
        TABLE,
        "hr_document_versions",
        ["document_id", "document_version_number"],
        ["document_id", "version_number"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        "fk_hr_policy_preceding_edition",
        TABLE,
        TABLE,
        ["supersedes_policy_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.create_check_constraint(
        op.f(CHECK),
        TABLE,
        "document_version_number IS NULL OR document_id IS NOT NULL",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_policy_documents "
            "WHERE document_version_number IS NOT NULL OR supersedes_policy_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot remove retained policy edition or exact document references.")
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.drop_constraint("fk_hr_policy_preceding_edition", TABLE, type_="foreignkey")
    op.drop_constraint("fk_hr_policy_exact_version", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "supersedes_policy_id")
    op.drop_column(TABLE, "document_version_number")
