"""Persist requisition rejection reasons and offer validity/versioning.

Revision ID: 202605310014
Revises: 202605310013
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310014"
down_revision: str | None = "202605310013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_requisitions", sa.Column("rejection_reason", sa.Text(), nullable=True))

    op.add_column("hr_offers", sa.Column("valid_until", sa.Date(), nullable=True))
    op.add_column(
        "hr_offers",
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("hr_offers", sa.Column("supersedes_offer_id", sa.Uuid(), nullable=True))
    op.add_column("hr_offers", sa.Column("superseded_by_id", sa.Uuid(), nullable=True))
    op.add_column(
        "hr_offers", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_hr_offers_supersedes_offer",
        "hr_offers",
        "hr_offers",
        ["supersedes_offer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_hr_offers_superseded_by_offer",
        "hr_offers",
        "hr_offers",
        ["superseded_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "version_positive",
        "hr_offers",
        "version_number >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("version_positive", "hr_offers", type_="check")
    op.drop_constraint("fk_hr_offers_superseded_by_offer", "hr_offers", type_="foreignkey")
    op.drop_constraint("fk_hr_offers_supersedes_offer", "hr_offers", type_="foreignkey")
    for column in (
        "superseded_at",
        "superseded_by_id",
        "supersedes_offer_id",
        "version_number",
        "valid_until",
    ):
        op.drop_column("hr_offers", column)
    op.drop_column("hr_requisitions", "rejection_reason")
