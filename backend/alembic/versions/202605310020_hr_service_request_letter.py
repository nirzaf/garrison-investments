"""Reference a reviewed issued letter from a completed HR service request."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310020"
down_revision: str | None = "202605310019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_hr_requests", sa.Column("generated_letter_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_hr_request_generated_letter",
        "hr_hr_requests",
        "hr_issued_letters",
        ["generated_letter_id"],
        ["id"],
        ondelete="RESTRICT",
        postgresql_not_valid=True,
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_hr_requests WHERE generated_letter_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot drop references to retained HR response letters.")
    op.drop_constraint("fk_hr_request_generated_letter", "hr_hr_requests", type_="foreignkey")
    op.drop_column("hr_hr_requests", "generated_letter_id")
