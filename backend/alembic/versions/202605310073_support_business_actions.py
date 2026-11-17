"""Add reviewed, case-scoped business authentication interventions."""

import sqlalchemy as sa

from alembic import op

revision = "202605310073"
down_revision = "202605310072"
branch_labels = None
depends_on = None


def _ref(name: str, table: str, *, key: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"),
        nullable=False,
        primary_key=key,
    )


def _time(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime','operator.manage','cases.manage','health.read',"
        "'directory.read','account.request')",
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
        "'account.request') AND enable IS NOT NULL)",
    )
    op.create_table(
        "support_business_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("case_id", "support_cases"),
        _ref("requester_id", "support_operators"),
        sa.Column("requester_epoch", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_revision", sa.Integer(), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("command_key", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        _time("expires_at"),
        _time("applied_at", nullable=True),
        sa.CheckConstraint("kind IN ('revoke_sessions', 'unlock')", name="kind"),
        sa.UniqueConstraint("case_id", "requester_id", "command_key"),
    )
    op.create_table(
        "support_business_approvals",
        _ref("action_id", "support_business_actions", key=True),
        _ref("reviewer_id", "support_operators", key=True),
        sa.Column("reviewer_epoch", sa.BigInteger(), nullable=False),
        _time("occurred_at"),
        sa.Column("request_id", sa.String(64), nullable=False),
    )
    op.create_table(
        "support_business_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("action_id", "support_business_actions"),
        _ref("session_id", "support_sessions"),
        sa.Column("stage", sa.String(8), nullable=False),
        sa.Column("challenge", sa.LargeBinary(32), nullable=False),
        _time("expires_at"),
        _time("consumed_at", nullable=True),
        sa.CheckConstraint("stage IN ('review', 'execute')", name="stage"),
    )
    op.create_table(
        "support_business_contacts",
        _ref("action_id", "support_business_actions", key=True),
        _ref("verifier_id", "support_operators"),
        sa.Column("verifier_epoch", sa.BigInteger(), nullable=False),
        sa.Column("contact_ref", sa.Uuid(), unique=True, nullable=False),
        sa.Column("action_digest", sa.String(64), nullable=False),
        _time("verified_at"),
        _time("expires_at"),
    )
    op.create_table(
        "support_business_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("action_id", "support_business_actions"),
        _ref("actor_id", "support_operators"),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        _time("occurred_at"),
        sa.CheckConstraint("event IN ('proposed', 'proof_denied', 'applied')", name="event"),
    )
    for table in (
        "support_business_approvals",
        "support_business_contacts",
        "support_business_events",
    ):
        op.execute(
            f"CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
        )
    for table in (
        "support_business_actions",
        "support_business_approvals",
        "support_business_contacts",
        "support_business_events",
    ):
        op.execute(
            f"CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
        )
    op.execute("""
        CREATE FUNCTION preserve_support_business_action() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.applied_at IS NOT NULL OR NEW.applied_at IS NULL
                OR (to_jsonb(NEW) - 'applied_at') IS DISTINCT FROM (to_jsonb(OLD) - 'applied_at')
            THEN
                RAISE EXCEPTION 'Support business action is immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute(
        "CREATE TRIGGER support_business_action_immutable BEFORE UPDATE "
        "ON support_business_actions "
        "FOR EACH ROW EXECUTE FUNCTION preserve_support_business_action()"
    )
    op.execute(
        "CREATE TRIGGER support_business_action_no_delete BEFORE DELETE "
        "ON support_business_actions "
        "FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support business decisions and authentication evidence.")
