"""Add reviewed business subject assignment and restricted directory reads."""

import sqlalchemy as sa

from alembic import op

revision = "202605310071"
down_revision = "202605310070"
branch_labels = None
depends_on = None

_SCOPE_CONSTRAINT = (
    "(kind IN ('member_add', 'member_remove') AND member_id IS NOT NULL"
    " AND source_event_id IS NULL AND subject_user_id IS NULL)"
    " OR (kind IN ('evidence_link', 'verify') AND member_id IS NULL"
    " AND source_event_id IS NOT NULL AND subject_user_id IS NULL)"
    " OR (kind IN ('close', 'subject_remove') AND member_id IS NULL"
    " AND source_event_id IS NULL AND subject_user_id IS NULL)"
    " OR (kind = 'subject_set' AND member_id IS NULL AND source_event_id IS NULL"
    " AND subject_user_id IS NOT NULL)"
)


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime', 'operator.manage', 'cases.manage', 'health.read', "
        "'directory.read')",
    )
    op.drop_constraint(
        op.f("ck_support_custody_actions_bounded_action"), "support_custody_actions", type_="check"
    )
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind IN ('suspend', 'enroll', 'recover') AND capability IS NULL AND enable IS NULL) OR "
        "(kind = 'grant_change' AND capability IS NOT NULL AND "
        "capability IN ('cases.manage', 'logs.runtime', 'health.read', 'directory.read') "
        "AND enable IS NOT NULL)",
    )
    op.add_column("support_case_actions", sa.Column("subject_user_id", sa.Uuid()))
    op.drop_constraint(
        op.f("ck_support_case_actions_payload"), "support_case_actions", type_="check"
    )
    op.create_check_constraint("payload", "support_case_actions", _SCOPE_CONSTRAINT)
    op.execute("""
        CREATE FUNCTION preserve_support_case_action() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.applied_at IS NOT NULL OR NEW.applied_at IS NULL
                OR (to_jsonb(NEW) - ARRAY[
                    'reviewer_id','applied_at','source_request_id','source_status'
                ]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[
                    'reviewer_id','applied_at','source_request_id','source_status'
                ])
            THEN
                RAISE EXCEPTION 'Support case proposal and applied receipt are immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute(
        "CREATE TRIGGER support_case_action_immutable BEFORE UPDATE ON support_case_actions "
        "FOR EACH ROW EXECUTE FUNCTION preserve_support_case_action()"
    )
    for suffix, event, scope in (
        ("no_delete", "DELETE", "ROW"),
        ("no_truncate", "TRUNCATE", "STATEMENT"),
    ):
        op.execute(
            f"CREATE TRIGGER support_case_action_{suffix} BEFORE {event} ON support_case_actions "
            f"FOR EACH {scope} EXECUTE FUNCTION prevent_support_audit_change()"
        )
    op.create_table(
        "support_case_subjects",
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
    )
    op.create_table(
        "support_directory_reads",
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
        sa.Column("subject_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_support_directory_reads_operator_occurred",
        "support_directory_reads",
        ["operator_id", "occurred_at"],
    )
    for suffix, event, scope in (
        ("append_only", "UPDATE OR DELETE", "ROW"),
        ("no_truncate", "TRUNCATE", "STATEMENT"),
    ):
        op.execute(
            f"CREATE TRIGGER support_audit_{suffix} BEFORE {event} ON support_directory_reads "
            f"FOR EACH {scope} EXECUTE FUNCTION prevent_support_audit_change()"
        )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed directory scope and access evidence during rollback.")
