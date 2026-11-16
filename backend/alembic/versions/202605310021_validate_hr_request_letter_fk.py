"""Validate the HR response letter foreign key."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310021"
down_revision: str | None = "202605310020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr_hr_requests VALIDATE CONSTRAINT fk_hr_request_generated_letter")


def downgrade() -> None:
    # Validation does not change write enforcement.
    pass
