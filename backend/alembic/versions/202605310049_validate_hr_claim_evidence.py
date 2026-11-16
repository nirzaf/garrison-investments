"""Validate reimbursement evidence references after the additive migration."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310049"
down_revision: str | None = "202605310048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hr_reimbursement_claims VALIDATE CONSTRAINT fk_hr_claim_receipt_version"
    )
    op.execute("ALTER TABLE hr_reimbursement_claims VALIDATE CONSTRAINT fk_hr_claim_submitter")


def downgrade() -> None:
    # The prior revision supports validated references.
    pass
