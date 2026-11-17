"""Record independently reviewed project boundaries for support cases."""

import sqlalchemy as sa

from alembic import op

revision = "202605310084"
down_revision = "202605310083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("support_case_actions", sa.Column("project_id", sa.Uuid()))
    op.drop_constraint(
        op.f("ck_support_case_actions_payload"), "support_case_actions", type_="check"
    )
    op.create_check_constraint(
        "payload",
        "support_case_actions",
        "(kind IN ('member_add', 'member_remove') AND member_id IS NOT NULL"
        " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NULL)"
        " OR (kind IN ('evidence_link', 'verify') AND member_id IS NULL"
        " AND source_event_id IS NOT NULL AND subject_user_id IS NULL AND project_id IS NULL)"
        " OR (kind IN ('close', 'subject_remove') AND member_id IS NULL"
        " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NULL)"
        " OR (kind = 'subject_set' AND member_id IS NULL AND source_event_id IS NULL"
        " AND subject_user_id IS NOT NULL AND project_id IS NULL)"
        " OR (kind IN ('project_add', 'project_remove') AND member_id IS NULL"
        " AND source_event_id IS NULL AND subject_user_id IS NULL AND project_id IS NOT NULL)",
    )
    op.create_table(
        "support_case_projects",
        sa.Column(
            "case_id", sa.Uuid(), sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("project_id", sa.Uuid(), primary_key=True),
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed project scope and case audit evidence.")
