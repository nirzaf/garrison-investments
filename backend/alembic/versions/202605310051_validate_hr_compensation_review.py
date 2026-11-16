"""Validate compensation review constraints after the additive migration."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310051"
down_revision: str | None = "202605310050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr_compensation_terms VALIDATE CONSTRAINT fk_hr_compensation_proposer")
    op.execute(
        "ALTER TABLE hr_compensation_terms "
        "VALIDATE CONSTRAINT ck_hr_compensation_terms_hr_compensation_approval_status"
    )


def downgrade() -> None:
    # The prior revision supports validated constraints.
    pass
