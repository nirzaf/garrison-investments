"""Add independently reviewed support operator suspension."""

import sqlalchemy as sa

from alembic import op

revision = "202605310065"
down_revision = "202605310064"
branch_labels = None
depends_on = None


def _ref(name: str, table: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable
    )


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime', 'operator.manage')",
    )
    op.create_table(
        "support_suspensions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("target_id", "support_operators"),
        _ref("requester_id", "support_operators"),
        _ref("reviewer_id", "support_operators", nullable=True),
        sa.Column("target_epoch", sa.Integer(), nullable=False),
        sa.Column("requester_epoch", sa.Integer(), nullable=False),
        sa.Column("reviewer_epoch", sa.Integer()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("target_id <> requester_id", name="distinct_target"),
        sa.CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id NOT IN (target_id, requester_id)",
            name="independent_reviewer",
        ),
    )
    op.create_table(
        "support_suspension_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("suspension_id", "support_suspensions"),
        _ref("session_id", "support_sessions"),
        sa.Column("stage", sa.String(8), nullable=False),
        sa.Column("challenge", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("stage IN ('review', 'execute')", name="stage"),
    )
    op.create_table(
        "support_suspension_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("suspension_id", "support_suspensions"),
        _ref("actor_id", "support_operators"),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('proposed', 'reviewed', 'executed', 'proof_denied', 'floor_denied')",
            name="action",
        ),
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_suspension_events FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE "
        "ON support_suspension_events FOR EACH STATEMENT "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support custody decisions and audit evidence during rollback.")
