"""Retain the exact vault file attached to an offer version."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310043"
down_revision: str | None = "202605310042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_offers", sa.Column("document_version_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_hr_offer_document_version",
        "hr_offers",
        "hr_document_versions",
        ["document_version_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM hr_offers WHERE document_version_id IS NOT NULL)")
    ):
        raise RuntimeError("Cannot remove retained offer document references.")
    op.drop_constraint("fk_hr_offer_document_version", "hr_offers", type_="foreignkey")
    op.drop_column("hr_offers", "document_version_id")
