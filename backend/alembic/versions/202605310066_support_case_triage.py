"""Add support case metadata and append-only triage events."""

import sqlalchemy as sa

from alembic import op

revision = "202605310066"
down_revision = "202605310065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime', 'operator.manage', 'cases.manage')",
    )
    op.add_column("support_cases", sa.Column("external_ref", sa.String(120)))
    op.add_column("support_cases", sa.Column("owner_id", sa.Uuid()))
    op.add_column("support_cases", sa.Column("severity", sa.String(8)))
    op.add_column("support_cases", sa.Column("reason_code", sa.String(24)))
    op.add_column(
        "support_cases", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_foreign_key(
        None, "support_cases", "support_operators", ["owner_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_unique_constraint(None, "support_cases", ["external_ref"])
    op.create_check_constraint("revision", "support_cases", "revision >= 1")
    op.create_check_constraint(
        "metadata",
        "support_cases",
        "(owner_id IS NULL AND external_ref IS NULL AND severity IS NULL AND reason_code IS NULL)"
        " OR (owner_id IS NOT NULL AND external_ref IS NOT NULL AND severity IS NOT NULL"
        " AND reason_code IS NOT NULL)",
    )
    op.create_check_constraint(
        "severity", "support_cases", "severity IN ('low', 'medium', 'high', 'critical')"
    )
    op.create_check_constraint(
        "reason_code",
        "support_cases",
        "reason_code IN ('availability', 'access', 'functional', 'data_integrity')",
    )
    op.create_index(
        "ix_support_case_members_operator_case", "support_case_members", ["operator_id", "case_id"]
    )
    op.create_table(
        "support_case_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operator_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(24)),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('created', 'read', 'transitioned')", name="action"),
    )
    op.create_index(
        "ix_support_case_events_case_occurred", "support_case_events", ["case_id", "occurred_at"]
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_case_events FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE "
        "ON support_case_events FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support case and audit evidence during rollback.")
