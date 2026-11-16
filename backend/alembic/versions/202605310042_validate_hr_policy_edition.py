"""Validate the policy edition and exact-document references."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310042"
down_revision: str | None = "202605310041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for constraint in (
        "fk_hr_policy_exact_version",
        "fk_hr_policy_preceding_edition",
        "ck_hr_policy_documents_hr_policy_version_requires_document",
    ):
        op.execute(f"ALTER TABLE hr_policy_documents VALIDATE CONSTRAINT {constraint}")


def downgrade() -> None:
    # Validation does not change write enforcement.
    pass
