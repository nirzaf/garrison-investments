"""Persist notification email dispatch and retry state."""

import sqlalchemy as sa

from alembic import op

revision = "202605310116"
down_revision = "202605310115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("task_outbox", sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("task_outbox", sa.Column("lease_until", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_task_outbox_notification_due",
        "task_outbox",
        ["next_attempt_at", "created_at", "id"],
        postgresql_where=sa.text(
            "task_name = 'send_email_notification' AND status = 'pending'"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_task_outbox_notification_due", table_name="task_outbox")
    op.drop_column("task_outbox", "lease_until")
    op.drop_column("task_outbox", "next_attempt_at")
