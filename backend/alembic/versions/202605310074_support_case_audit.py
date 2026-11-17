"""Add bounded case audit access with separate disclosure records."""

import sqlalchemy as sa

from alembic import op

revision = "202605310074"
down_revision = "202605310073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime','operator.manage','cases.manage','health.read',"
        "'directory.read','account.request','logs.audit')",
    )
    op.drop_constraint(
        op.f("ck_support_custody_actions_bounded_action"), "support_custody_actions", type_="check"
    )
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind IN ('suspend','enroll','recover') AND capability IS NULL AND enable IS NULL)"
        " OR (kind = 'grant_change' AND capability IS NOT NULL AND"
        " capability IN ('cases.manage','logs.runtime','health.read','directory.read',"
        "'account.request','logs.audit') AND enable IS NOT NULL)",
    )
    op.create_table(
        "support_case_audit_reads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "operator_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("event_count BETWEEN 0 AND 100", name="event_count"),
    )
    op.create_index(
        "ix_support_case_audit_reads_operator_occurred",
        "support_case_audit_reads",
        ["operator_id", "occurred_at"],
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_case_audit_reads "
        "FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE ON support_case_audit_reads "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support case audit disclosures.")
