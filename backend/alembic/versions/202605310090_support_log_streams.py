"""Bound and record case-scoped log streams across API workers."""

import sqlalchemy as sa

from alembic import op

revision = "202605310090"
down_revision = "202605310089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_log_streams",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "operator_id", sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "session_id", sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column(
            "case_id", sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"), nullable=False,
        ),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("source_request_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_support_log_streams_operator_expiry",
            "support_log_streams",
            ["operator_id", "expires_at"],
            postgresql_concurrently=True,
        )
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime','operator.manage','cases.manage','health.read',"
        "'directory.read','account.request','logs.audit','simulation.start','logs.stream')",
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
        "'account.request','logs.audit','simulation.start','logs.stream') AND enable IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support log stream access records.")
