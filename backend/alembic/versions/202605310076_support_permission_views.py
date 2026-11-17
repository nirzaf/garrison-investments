"""Add leased, independently reviewed permission explanations."""

import sqlalchemy as sa

from alembic import op

revision = "202605310076"
down_revision = "202605310075"
branch_labels = None
depends_on = None


def _ref(name: str, table: str, *, primary_key: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.Uuid(),
        sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"),
        nullable=False,
        primary_key=primary_key,
    )


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime','operator.manage','cases.manage','health.read',"
        "'directory.read','account.request','logs.audit','simulation.start')",
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
        "'account.request','logs.audit','simulation.start') AND enable IS NOT NULL)",
    )
    op.add_column("support_business_actions", sa.Column("permission_key", sa.String(64)))
    op.add_column(
        "support_business_actions",
        sa.Column("permission_session_id", sa.Uuid(), sa.ForeignKey("support_sessions.id")),
    )
    op.drop_constraint(
        op.f("ck_support_business_actions_kind"), "support_business_actions", type_="check"
    )
    op.create_check_constraint(
        "kind",
        "support_business_actions",
        "(kind IN ('revoke_sessions','unlock','disable','reactivate') AND permission_key IS NULL"
        " AND permission_session_id IS NULL)"
        " OR (kind = 'permission_view' AND permission_key IS NOT NULL"
        " AND permission_session_id IS NOT NULL)",
    )
    op.create_table(
        "support_permission_views",
        _ref("id", "support_business_actions", primary_key=True),
        _ref("session_id", "support_sessions"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_support_permission_views_session_expiry",
        "support_permission_views",
        ["session_id", "expires_at"],
    )
    op.create_table(
        "support_permission_view_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _ref("view_id", "support_permission_views"),
        _ref("actor_id", "support_operators"),
        sa.Column("event", sa.String(12), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.CheckConstraint("event IN ('opened', 'read', 'ended')", name="event"),
    )
    for name, event, level in (
        ("append_only", "UPDATE OR DELETE", "ROW"),
        ("no_truncate", "TRUNCATE", "STATEMENT"),
    ):
        op.execute(
            f"CREATE TRIGGER support_audit_{name} BEFORE {event} ON support_permission_view_events "
            f"FOR EACH {level} EXECUTE FUNCTION prevent_support_audit_change()"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve approved support views and disclosure evidence.")
