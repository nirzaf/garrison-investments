"""Record independently reviewed candidate correspondence."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310039"
down_revision: str | None = "202605310038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "hr_candidate_correspondence"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("hr_applications.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "template_id",
            sa.Uuid(),
            sa.ForeignKey("hr_letter_templates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("content_encrypted", sa.Text(), nullable=False),
        sa.Column("status", sa.String(12), server_default="draft", nullable=False),
        sa.Column(
            "prepared_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("reason_encrypted", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND decided_by IS NULL AND decided_at IS NULL "
            "AND reason_encrypted IS NULL) OR "
            "(status IN ('approved', 'rejected') AND decided_by IS NOT NULL "
            "AND decided_at IS NOT NULL AND decided_by <> prepared_by "
            "AND ((status = 'rejected') = (reason_encrypted IS NOT NULL)))",
            name="candidate_correspondence_decision",
        ),
    )
    op.create_index(
        "ix_hr_candidate_correspondence_application", TABLE, ["application_id", "created_at", "id"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_candidate_correspondence)")):
        raise RuntimeError("Cannot remove retained candidate correspondence.")
    op.drop_table(TABLE)
