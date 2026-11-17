"""Add support oversight capabilities, append-only disclosure audit, and backup receipts."""

import sqlalchemy as sa

from alembic import op

revision = "202605310093"
down_revision = "202605310092"
branch_labels = None
depends_on = None

_GRANT_CAPABILITIES = (
    "'logs.runtime', 'operator.manage', 'cases.manage', 'health.read', 'directory.read', "
    "'account.request', 'logs.audit', 'simulation.start', 'logs.stream', 'logs.export', "
    "'overview.company.read', 'overview.projects.read', 'overview.workforce.read', "
    "'overview.inventory.read', 'overview.suppliers.read', 'overview.documents.read', "
    "'overview.finance.read', 'overview.approvals.read', 'jobs.read', 'backups.read', "
    "'config.read', 'incidents.read'"
)

_CUSTODY_GRANT_CAPABILITIES = (
    "'cases.manage', 'logs.runtime', 'logs.stream', 'logs.export', 'health.read', "
    "'directory.read', 'account.request', 'logs.audit', 'simulation.start', "
    "'overview.company.read', 'overview.projects.read', 'overview.workforce.read', "
    "'overview.inventory.read', 'overview.suppliers.read', 'overview.documents.read', "
    "'overview.finance.read', 'overview.approvals.read', 'jobs.read', 'backups.read', "
    "'config.read', 'incidents.read'"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        f"capability IN ({_GRANT_CAPABILITIES})",
    )
    op.drop_constraint(
        op.f("ck_support_custody_actions_bounded_action"), "support_custody_actions", type_="check"
    )
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind IN ('suspend', 'enroll', 'recover') AND capability IS NULL AND enable IS NULL) OR "
        "(kind = 'grant_change' AND capability IS NOT NULL AND "
        f"capability IN ({_CUSTODY_GRANT_CAPABILITIES}) AND enable IS NOT NULL)",
    )
    op.create_table(
        "support_oversight_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operator_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("surface", sa.String(32), nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "surface IN ('overview_company', 'overview_projects', 'overview_workforce', "
            "'overview_inventory', 'overview_suppliers', 'overview_documents', "
            "'overview_finance', 'overview_approvals', 'jobs', 'backups', 'config', "
            "'incidents', 'policy_explain')",
            name="surface",
        ),
        sa.CheckConstraint("action IN ('requested', 'returned')", name="action"),
    )
    op.create_index(
        "ix_support_oversight_events_operator_occurred",
        "support_oversight_events",
        ["operator_id", "occurred_at"],
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_oversight_events FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE "
        "ON support_oversight_events FOR EACH STATEMENT "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )

    op.create_table(
        "support_backup_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("receipt_kind", sa.String(32), nullable=False),
        sa.Column("backup_set_id", sa.String(80), nullable=True),
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("target_domain", sa.String(32), nullable=False),
        sa.Column("covers_database", sa.Boolean(), nullable=False),
        sa.Column("covers_objects", sa.Boolean(), nullable=False),
        sa.Column("outcome", sa.String(12), nullable=False),
        sa.Column("rpo_minutes", sa.Integer(), nullable=True),
        sa.Column("rto_minutes", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signer_key_id", sa.String(80), nullable=True),
        sa.Column("recorded_by", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "receipt_kind IN ('scheduled_db_attempt', 'authenticated_backup_set', 'restore_drill')",
            name="receipt_kind",
        ),
        sa.CheckConstraint(
            "target_domain IN ('local_host', 'independent_offhost', 'isolated_restore')",
            name="target_domain",
        ),
        sa.CheckConstraint("outcome IN ('pass', 'fail', 'unknown')", name="outcome"),
    )
    op.create_index(
        "ix_support_backup_receipts_kind_captured",
        "support_backup_receipts",
        ["receipt_kind", "captured_at"],
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_backup_receipts FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE "
        "ON support_backup_receipts FOR EACH STATEMENT "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support oversight audit and backup receipt records.")
