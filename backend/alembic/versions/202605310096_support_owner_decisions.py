"""Preserve paired reviews and distinguish owner-confirmed case and export decisions."""

import sqlalchemy as sa

from alembic import op

revision = "202605310096"
down_revision = "202605310095"
branch_labels = None
depends_on = None

_DECISIONS = {
    "support_case_actions": (
        "(authorization_mode = 'paired' AND (applied_at IS NULL) = (reviewer_id IS "
        "NULL)) OR (authorization_mode = 'single_owner' AND reviewer_id IS NULL)"
    ),
    "support_evidence_exports": (
        "(approved_at IS NULL) = (review_request_id IS NULL) AND (downloaded_at IS "
        "NULL) = (download_request_id IS NULL) AND (downloaded_at IS NULL OR "
        "approved_at IS NOT NULL) AND ((authorization_mode = 'paired' AND "
        "(approved_at IS NULL) = (reviewer_id IS NULL) AND (approved_at IS NULL) = "
        "(reviewer_epoch IS NULL)) OR (authorization_mode = 'single_owner' AND "
        "reviewer_id IS NULL AND reviewer_epoch IS NULL))"
    ),
}


def upgrade() -> None:
    for table, constraint in _DECISIONS.items():
        op.add_column(
            table,
            sa.Column("authorization_mode", sa.String(20), nullable=False, server_default="paired"),
        )
        op.drop_constraint(op.f(f"ck_{table}_decision"), table, type_="check")
        op.create_check_constraint("decision", table, constraint)


def downgrade() -> None:
    raise RuntimeError("Owner-confirmed decisions require a forward recovery plan.")
