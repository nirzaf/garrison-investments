"""Add non-blocking leave workflow indexes after checking existing decisions."""

import sqlalchemy as sa

from alembic import op

revision = "202605310114"
down_revision = "202605310113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            "SELECT reference_request_id, entry_type "
            "FROM hr_leave_ledger "
            "WHERE reference_request_id IS NOT NULL "
            "AND entry_type IN ('taken', 'reversal') "
            "GROUP BY reference_request_id, entry_type "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Leave decision ledger contains duplicate taken/reversal entries; "
            "reconcile them before applying leave workflow uniqueness."
        )

    duplicate_due_date = connection.execute(
        sa.text(
            "SELECT employee_id, leave_type_id, due_date FROM hr_leave_accruals "
            "WHERE due_date IS NOT NULL "
            "GROUP BY employee_id, leave_type_id, due_date "
            "HAVING count(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate_due_date is not None:
        raise RuntimeError(
            "Leave accruals contain duplicate due-date receipts; reconcile them "
            "before applying leave workflow uniqueness."
        )

    with op.get_context().autocommit_block():
        op.create_index(
            "uq_hr_leave_accrual_due_date",
            "hr_leave_accruals",
            ["employee_id", "leave_type_id", "due_date"],
            unique=True,
            postgresql_where=sa.text("due_date IS NOT NULL"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_hr_leave_requests_supervisor_pending",
            "hr_leave_requests",
            ["assigned_supervisor_user_id", "start_date", "id"],
            postgresql_where=sa.text("status = 'submitted' AND approval_route = 'supervisor'"),
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_leave_notification_event",
            "notifications",
            ["user_id", "reference_id", "event_revision", "event_code"],
            unique=True,
            postgresql_where=sa.text(
                "reference_type = 'hr_leave_request' AND event_code IS NOT NULL"
            ),
            postgresql_concurrently=True,
        )
        op.create_index(
            "uq_hr_leave_request_ledger_decision",
            "hr_leave_ledger",
            ["reference_request_id", "entry_type"],
            unique=True,
            postgresql_where=sa.text(
                "reference_request_id IS NOT NULL AND entry_type IN ('taken', 'reversal')"
            ),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "uq_hr_leave_request_ledger_decision",
            table_name="hr_leave_ledger",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_leave_notification_event",
            table_name="notifications",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_hr_leave_requests_supervisor_pending",
            table_name="hr_leave_requests",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "uq_hr_leave_accrual_due_date",
            table_name="hr_leave_accruals",
            postgresql_concurrently=True,
        )
