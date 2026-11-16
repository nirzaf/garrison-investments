"""Retain reimbursement submitter, exact receipt and external outcome reference."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision: str = "202605310048"
down_revision: str | None = "202605310047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hr_reimbursement_claims"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("receipt_version_id", UUID(as_uuid=True)))
    op.add_column(TABLE, sa.Column("submitted_by_id", UUID(as_uuid=True)))
    op.add_column(TABLE, sa.Column("settlement_reference", sa.String(100)))
    op.create_foreign_key(
        "fk_hr_claim_receipt_version",
        TABLE,
        "hr_document_versions",
        ["receipt_version_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )
    op.create_foreign_key(
        "fk_hr_claim_submitter",
        TABLE,
        "users",
        ["submitted_by_id"],
        ["id"],
        ondelete="SET NULL",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_reimbursement_claims WHERE "
            "receipt_version_id IS NOT NULL OR submitted_by_id IS NOT NULL "
            "OR settlement_reference IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard retained reimbursement evidence.")
    op.drop_constraint("fk_hr_claim_submitter", TABLE, type_="foreignkey")
    op.drop_constraint("fk_hr_claim_receipt_version", TABLE, type_="foreignkey")
    op.drop_column(TABLE, "settlement_reference")
    op.drop_column(TABLE, "submitted_by_id")
    op.drop_column(TABLE, "receipt_version_id")
