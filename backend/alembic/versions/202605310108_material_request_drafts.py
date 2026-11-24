"""Persist editable material request drafts and correction revision links."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "202605310108"
down_revision = "202605310107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("material_requests", sa.Column("draft_payload", JSONB(), nullable=True))
    op.add_column("material_requests", sa.Column("correction_target_id", sa.Uuid(), nullable=True))
    op.add_column(
        "material_requests", sa.Column("correction_expected_revision", sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        "fk_material_requests_draft_target",
        "material_requests",
        "material_requests",
        ["correction_target_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_material_requests_draft_target", "material_requests", type_="foreignkey")
    op.drop_column("material_requests", "correction_expected_revision")
    op.drop_column("material_requests", "correction_target_id")
    op.drop_column("material_requests", "draft_payload")
