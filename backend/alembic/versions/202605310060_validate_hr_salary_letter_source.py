"""Validate the source reference for salary confirmations."""

from alembic import op

revision = "202605310060"
down_revision = "202605310059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE hr_issued_letters VALIDATE CONSTRAINT fk_hr_letter_compensation_term"
    )


def downgrade() -> None:
    pass
