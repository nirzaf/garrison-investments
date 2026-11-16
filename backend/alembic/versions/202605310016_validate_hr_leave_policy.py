"""Validate the leave policy review constraints."""

from collections.abc import Sequence

from alembic import op

revision: str = "202605310016"
down_revision: str | None = "202605310015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE hr_leave_policies VALIDATE CONSTRAINT fk_hr_leave_policy_creator")
    op.execute(
        "ALTER TABLE hr_leave_policies VALIDATE CONSTRAINT "
        "ck_hr_leave_policies_hr_leave_policy_status"
    )
    op.execute(
        "ALTER TABLE hr_leave_policies VALIDATE CONSTRAINT "
        "ck_hr_leave_policies_hr_leave_policy_effective_window"
    )


def downgrade() -> None:
    # A validated constraint enforces the same writes as its unvalidated form.
    pass
