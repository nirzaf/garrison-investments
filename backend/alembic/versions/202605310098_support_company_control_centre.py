"""Add support auth assurance tracking, company control capabilities, and command receipts."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605310098"
down_revision = "202605310097"
branch_labels = None
depends_on = None

_GRANT_CAPABILITIES = (
    "'logs.runtime', 'operator.manage', 'cases.manage', 'health.read', 'directory.read', "
    "'account.request', 'logs.audit', 'simulation.start', 'logs.stream', 'logs.export', "
    "'overview.company.read', 'overview.projects.read', 'overview.workforce.read', "
    "'overview.inventory.read', 'overview.suppliers.read', 'overview.documents.read', "
    "'overview.finance.read', 'overview.approvals.read', 'jobs.read', 'backups.read', "
    "'config.read', 'incidents.read', "
    "'company.directory.read', 'company.accounts.manage', 'company.access.assign', "
    "'company.sessions.read', 'company.sessions.revoke', 'company.settings.manage', "
    "'company.jobs.retry', 'company.data.inspect'"
)

_CUSTODY_GRANT_CAPABILITIES = (
    "'cases.manage', 'logs.runtime', 'logs.stream', 'logs.export', 'health.read', "
    "'directory.read', 'account.request', 'logs.audit', 'simulation.start', "
    "'overview.company.read', 'overview.projects.read', 'overview.workforce.read', "
    "'overview.inventory.read', 'overview.suppliers.read', 'overview.documents.read', "
    "'overview.finance.read', 'overview.approvals.read', 'jobs.read', 'backups.read', "
    "'config.read', 'incidents.read', "
    "'company.directory.read', 'company.accounts.manage', 'company.access.assign', "
    "'company.sessions.read', 'company.sessions.revoke', 'company.settings.manage', "
    "'company.jobs.retry', 'company.data.inspect'"
)

_OVERSIGHT_SURFACES = (
    "'overview_company', 'overview_projects', 'overview_workforce', "
    "'overview_inventory', 'overview_suppliers', 'overview_documents', "
    "'overview_finance', 'overview_approvals', 'jobs', 'backups', 'config', "
    "'incidents', 'policy_explain', "
    "'company_context', 'company_directory', 'company_user_profile', "
    "'company_user_access', 'company_user_sessions', 'company_user_activity', "
    "'company_settings', 'company_data_inspector'"
)

_COMMAND_KINDS = (
    "'create_business_account', 'set_account_state', 'unlock_account', "
    "'change_business_role', 'change_project_membership', 'request_account_recovery', "
    "'revoke_business_session', 'update_safe_setting', 'retry_safe_job', "
    "'bulk_account_lifecycle'"
)

_COMMAND_STATUSES = (
    "'planned', 'expired', 'succeeded', 'delivery_pending', 'delivery_failed', 'rejected'"
)

_COMMAND_EVENTS = (
    "'planned', 'proof_issued', 'proof_denied', 'executed', 'replayed', 'rejected', "
    "'delivery_updated'"
)

_SAFE_SETTINGS = (
    "'company_display_name', 'support_banner_notice', 'default_directory_page_size', "
    "'maintenance_window_notice'"
)


def upgrade() -> None:
    op.add_column(
        "support_login_challenges",
        sa.Column("auth_method", sa.String(24), nullable=False, server_default="passkey"),
    )
    op.create_check_constraint(
        "auth_method",
        "support_login_challenges",
        "auth_method IN ('passkey', 'email_otp_only')",
    )
    op.add_column(
        "support_sessions",
        sa.Column("auth_method", sa.String(24), nullable=False, server_default="passkey"),
    )
    op.create_check_constraint(
        "auth_method",
        "support_sessions",
        "auth_method IN ('passkey', 'email_otp_only')",
    )

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
    op.drop_constraint(
        op.f("ck_support_oversight_events_surface"), "support_oversight_events", type_="check"
    )
    op.create_check_constraint(
        "surface",
        "support_oversight_events",
        f"surface IN ({_OVERSIGHT_SURFACES})",
    )

    op.create_table(
        "support_admin_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operator_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("operator_epoch", sa.BigInteger(), nullable=False),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("authorization_mode", sa.String(16), nullable=False),
        sa.Column("command_kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=True),
        sa.Column("target_revision", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("project_revision", sa.Integer(), nullable=True),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("plan_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "operator_id",
            "command_kind",
            "idempotency_key",
            name="uq_support_admin_commands_operator_kind_key",
        ),
        sa.CheckConstraint(f"command_kind IN ({_COMMAND_KINDS})", name="command_kind"),
        sa.CheckConstraint(f"status IN ({_COMMAND_STATUSES})", name="status"),
        sa.CheckConstraint(
            "authorization_mode IN ('single_owner', 'paired')",
            name="authorization_mode",
        ),
    )
    op.create_index(
        "ix_support_admin_commands_target_created",
        "support_admin_commands",
        ["target_user_id", "created_at"],
    )
    op.create_index(
        "ix_support_admin_commands_operator_created",
        "support_admin_commands",
        ["operator_id", "created_at"],
    )

    op.create_table(
        "support_admin_command_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("support_admin_commands.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("challenge", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("octet_length(challenge) = 32", name="challenge_size"),
    )
    op.create_index(
        "ix_support_admin_command_proofs_command_id",
        "support_admin_command_proofs",
        ["command_id"],
    )

    op.create_table(
        "support_admin_command_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "command_id",
            sa.Uuid(),
            sa.ForeignKey("support_admin_commands.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"event IN ({_COMMAND_EVENTS})", name="event"),
    )
    op.create_index(
        "ix_support_admin_command_events_command_occurred",
        "support_admin_command_events",
        ["command_id", "occurred_at"],
    )

    op.create_table(
        "support_safe_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_by_operator_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by_command_id",
            sa.Uuid(),
            sa.ForeignKey("support_admin_commands.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"key IN ({_SAFE_SETTINGS})", name="key"),
        sa.CheckConstraint("revision >= 1", name="revision"),
    )

    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_admin_command_events FOR EACH ROW "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )
    for table in (
        "support_admin_commands",
        "support_admin_command_proofs",
        "support_admin_command_events",
        "support_safe_settings",
    ):
        op.execute(
            f"CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
        )
    op.execute(
        "CREATE TRIGGER support_admin_command_no_delete BEFORE DELETE "
        "ON support_admin_commands FOR EACH ROW "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        """
        CREATE FUNCTION preserve_support_admin_command() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (to_jsonb(NEW) - 'status' - 'result_json' - 'completed_at' - 'target_user_id')
                IS DISTINCT FROM
               (to_jsonb(OLD) - 'status' - 'result_json' - 'completed_at' - 'target_user_id')
            THEN
                RAISE EXCEPTION 'Support admin command plan fields are immutable';
            END IF;

            IF OLD.target_user_id IS NOT NULL
                AND NEW.target_user_id IS DISTINCT FROM OLD.target_user_id
            THEN
                RAISE EXCEPTION 'Support admin command target_user_id is immutable';
            END IF;

            IF OLD.status = 'planned' THEN
                IF NEW.status NOT IN (
                    'expired', 'succeeded', 'delivery_pending', 'delivery_failed', 'rejected'
                ) THEN
                    RAISE EXCEPTION 'Support admin command receipt is immutable';
                END IF;
                RETURN NEW;
            ELSIF OLD.status = 'delivery_pending' THEN
                IF NEW.status NOT IN ('succeeded', 'delivery_failed') THEN
                    RAISE EXCEPTION 'Support admin command receipt is immutable';
                END IF;
                RETURN NEW;
            END IF;

            RAISE EXCEPTION 'Support admin command receipt is immutable';
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER support_admin_command_immutable BEFORE UPDATE "
        "ON support_admin_commands FOR EACH ROW "
        "EXECUTE FUNCTION preserve_support_admin_command()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support command receipts and authentication assurance records.")
