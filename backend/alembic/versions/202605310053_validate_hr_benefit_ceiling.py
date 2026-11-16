"""Validate reimbursement coverage references."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310053"
down_revision: str | None = "202605310052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr_benefit_types VALIDATE CONSTRAINT fk_hr_benefit_policy_proposer")
    op.execute("ALTER TABLE hr_benefit_types VALIDATE CONSTRAINT fk_hr_benefit_policy_approver")
    op.execute(
        "ALTER TABLE hr_reimbursement_claims VALIDATE CONSTRAINT fk_hr_claim_benefit_assignment"
    )


def downgrade() -> None:
    pass
