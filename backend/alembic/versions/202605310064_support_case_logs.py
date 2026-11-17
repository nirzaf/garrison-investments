"""Scope support request evidence to explicit cases and retain access audit."""

import sqlalchemy as sa

from alembic import op

revision = "202605310064"
down_revision = "202605310063"
branch_labels = None
depends_on = None


def _ref(name: str, target: str, *, primary_key: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(target, ondelete="RESTRICT"),
        nullable=False,
        primary_key=primary_key,
    )


def upgrade() -> None:
    op.create_table(
        "support_operator_grants",
        _ref("operator_id", "support_operators.id", primary_key=True),
        sa.Column("capability", sa.String(32), primary_key=True),
        sa.CheckConstraint("capability = 'logs.runtime'", name="capability"),
    )
    op.create_table(
        "support_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.CheckConstraint(
            "status IN ('open','investigating','mitigated','verified','closed')", name="status"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "support_case_members",
        _ref("case_id", "support_cases.id", primary_key=True),
        _ref("operator_id", "support_operators.id", primary_key=True),
    )
    op.create_table(
        "support_case_requests",
        _ref("case_id", "support_cases.id", primary_key=True),
        sa.Column("request_id", sa.String(36), primary_key=True),
    )
    op.create_table(
        "support_log_reads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("operator_id", "support_operators.id"),
        _ref("case_id", "support_cases.id"),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("source_request_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filter_status_code", sa.Integer()),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count BETWEEN 0 AND 100", name="event_count"),
        sa.CheckConstraint("requested_limit BETWEEN 1 AND 100", name="requested_limit"),
        sa.CheckConstraint(
            "filter_status_code IS NULL OR filter_status_code BETWEEN 100 AND 599",
            name="filter_status_code",
        ),
    )
    op.create_index(
        "ix_support_log_reads_operator_occurred",
        "support_log_reads",
        ["operator_id", "occurred_at"],
    )
    op.execute("""
        CREATE FUNCTION prevent_support_audit_change() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Support audit records are append-only';
        END;
        $$;
    """)
    for table in ("support_auth_events", "support_log_reads"):
        op.execute(
            f"CREATE TRIGGER support_audit_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
        )
        op.execute(
            f"CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve technical case and audit evidence during rollback.")
