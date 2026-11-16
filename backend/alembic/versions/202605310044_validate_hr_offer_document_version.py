"""Validate the exact offer document reference."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310044"
down_revision: str | None = "202605310043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr_offers VALIDATE CONSTRAINT fk_hr_offer_document_version")


def downgrade() -> None:
    # Validation does not change write enforcement.
    pass
