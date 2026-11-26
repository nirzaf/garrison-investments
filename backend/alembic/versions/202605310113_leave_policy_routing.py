"""Add managed leave policy metadata and final approval routing."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605310113"
down_revision = "202605310112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hr_leave_policies",
        sa.Column("entitlement_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "hr_leave_types",
        sa.Column("policy_required", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("hr_leave_accruals", sa.Column("due_date", sa.Date(), nullable=True))
    op.add_column("hr_leave_requests", sa.Column("approval_route", sa.String(20), nullable=True))
    op.add_column(
        "hr_leave_requests",
        sa.Column(
            "assigned_supervisor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "hr_leave_requests", sa.Column("fallback_reason_code", sa.String(40), nullable=True)
    )
    op.add_column("hr_leave_requests", sa.Column("fallback_reason", sa.Text(), nullable=True))
    op.add_column(
        "hr_leave_requests",
        sa.Column(
            "fallback_recorded_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "hr_leave_requests",
        sa.Column("fallback_recorded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("hr_leave_requests", sa.Column("fallback_until", sa.Date(), nullable=True))
    op.create_check_constraint(
        "hr_leave_request_route_coherence",
        "hr_leave_requests",
        "approval_route IS NULL OR "
        "(approval_route = 'supervisor' AND assigned_supervisor_user_id IS NOT NULL "
        "AND fallback_reason_code IS NULL AND fallback_reason IS NULL "
        "AND fallback_recorded_by_id IS NULL AND fallback_recorded_at IS NULL "
        "AND fallback_until IS NULL) OR "
        "(approval_route = 'hr_fallback' AND fallback_reason_code IS NOT NULL "
        "AND fallback_reason IS NOT NULL AND fallback_recorded_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "hr_leave_request_fallback_reason",
        "hr_leave_requests",
        "fallback_reason_code IS NULL OR fallback_reason_code IN "
        "('manager_missing', 'manager_ineligible', 'manager_absent', "
        "'manager_temporarily_unavailable')",
    )
    op.add_column("notifications", sa.Column("event_code", sa.String(30), nullable=True))
    op.add_column("notifications", sa.Column("event_revision", sa.Integer(), nullable=True))
    op.create_table(
        "hr_leave_entitlement_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leave_year", sa.Integer(), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("verified_balance", sa.Numeric(6, 2), nullable=False),
        sa.Column(
            "recognized_due_dates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("supporting_reference", sa.String(200), nullable=False),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ledger_digest", sa.String(64), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("adjustment_ledger_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("leave_year BETWEEN 2020 AND 2100", name="hr_leave_baseline_year"),
        sa.CheckConstraint("verified_balance >= 0", name="hr_leave_baseline_balance"),
        sa.CheckConstraint(
            "length(btrim(supporting_reference)) > 0", name="hr_leave_baseline_reference"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(recognized_due_dates) = 'array'",
            name="hr_leave_baseline_due_dates",
        ),
        sa.ForeignKeyConstraint(["employee_id"], ["hr_employees.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["leave_type_id"], ["hr_leave_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["policy_id"], ["hr_leave_policies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["adjustment_ledger_id"], ["hr_leave_ledger.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "employee_id",
            "leave_type_id",
            "leave_year",
            name="uq_hr_leave_entitlement_baseline",
        ),
        sa.UniqueConstraint("adjustment_ledger_id", name="uq_hr_leave_baseline_adjustment"),
    )


def downgrade() -> None:
    op.drop_table("hr_leave_entitlement_baselines")
    op.drop_column("notifications", "event_revision")
    op.drop_column("notifications", "event_code")
    op.drop_column("hr_leave_types", "policy_required")
    op.drop_constraint(
        "hr_leave_request_fallback_reason", "hr_leave_requests", type_="check"
    )
    op.drop_constraint(
        "hr_leave_request_route_coherence", "hr_leave_requests", type_="check"
    )
    op.drop_column("hr_leave_requests", "fallback_until")
    op.drop_column("hr_leave_requests", "fallback_recorded_at")
    op.drop_column("hr_leave_requests", "fallback_recorded_by_id")
    op.drop_column("hr_leave_requests", "fallback_reason")
    op.drop_column("hr_leave_requests", "fallback_reason_code")
    op.drop_column("hr_leave_requests", "assigned_supervisor_user_id")
    op.drop_column("hr_leave_requests", "approval_route")
    op.drop_column("hr_leave_policies", "entitlement_rules")
