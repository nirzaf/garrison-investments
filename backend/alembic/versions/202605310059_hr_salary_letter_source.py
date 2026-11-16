"""Pin newly drafted salary confirmations to an approved compensation term."""

import sqlalchemy as sa

from alembic import op

revision = "202605310059"
down_revision = "202605310058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hr_issued_letters", sa.Column("compensation_term_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_hr_letter_compensation_term", "hr_issued_letters", "hr_compensation_terms",
        ["compensation_term_id"], ["id"], ondelete="RESTRICT", postgresql_not_valid=True,
    )


def downgrade() -> None:
    raise RuntimeError("Salary confirmation source records must be preserved.")
