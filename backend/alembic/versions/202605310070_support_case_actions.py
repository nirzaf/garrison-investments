"""Store reviewed case scope changes and independent closure receipts."""

import sqlalchemy as sa

from alembic import op

revision = "202605310070"
down_revision = "202605310069"
branch_labels = None
depends_on = None


def _reference(name: str, table: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable
    )


def upgrade() -> None:
    op.create_table(
        "support_case_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _reference("case_id", "support_cases"),
        _reference("requester_id", "support_operators"),
        _reference("reviewer_id", "support_operators", nullable=True),
        _reference("member_id", "support_operators", nullable=True),
        sa.Column("source_event_id", sa.Uuid()),
        sa.Column("source_request_id", sa.String(36)),
        sa.Column("source_status", sa.Integer()),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("case_revision", sa.Integer(), nullable=False),
        sa.Column("requester_epoch", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(kind IN ('member_add', 'member_remove') AND member_id IS NOT NULL"
            " AND source_event_id IS NULL) OR (kind IN ('evidence_link', 'verify')"
            " AND member_id IS NULL AND source_event_id IS NOT NULL)"
            " OR (kind = 'close' AND member_id IS NULL AND source_event_id IS NULL)",
            name="payload",
        ),
        sa.CheckConstraint("(applied_at IS NULL) = (reviewer_id IS NULL)", name="decision"),
        sa.CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id <> requester_id", name="independent"
        ),
    )
    op.create_index(
        "ix_support_case_actions_case_expiry", "support_case_actions", ["case_id", "expires_at"]
    )
    op.create_table(
        "support_case_action_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _reference("action_id", "support_case_actions"),
        _reference("session_id", "support_sessions"),
        sa.Column("challenge", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "support_case_action_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _reference("action_id", "support_case_actions"),
        _reference("actor_id", "support_operators"),
        sa.Column("event", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event IN ('requested', 'proof_denied', 'applied')", name="event"),
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE "
        "ON support_case_action_events FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE "
        "ON support_case_action_events FOR EACH STATEMENT "
        "EXECUTE FUNCTION prevent_support_audit_change()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed support case decisions during rollback.")
