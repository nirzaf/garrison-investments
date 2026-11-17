"""Add audited initial enrollment for exactly two technical custodians."""

import sqlalchemy as sa

from alembic import op

revision = "202605310086"
down_revision = "202605310085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_bootstrap",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "first_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "second_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("approval_digest", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("id = 1 AND first_id <> second_id", name="singleton_pair"),
    )
    op.create_table(
        "support_bootstrap_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "bootstrap_id",
            sa.Integer(),
            sa.ForeignKey("support_bootstrap.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "operator_id", sa.Uuid(), sa.ForeignKey("support_operators.id", ondelete="RESTRICT")
        ),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('started', 'invitations_issued', 'passkey_added', "
            "'registration_denied', 'activated')",
            name="action",
        ),
    )
    for event, scope in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        op.execute(
            f"CREATE TRIGGER support_bootstrap_events_no_{event.lower()} "
            f"BEFORE {event} ON support_bootstrap_events FOR EACH {scope} "
            "EXECUTE FUNCTION prevent_support_audit_change()"
        )
    op.execute("""
        CREATE FUNCTION finalize_support_bootstrap() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.activated_at IS NOT NULL OR NEW.activated_at IS NULL
                OR (to_jsonb(NEW) - 'activated_at') IS DISTINCT FROM
                   (to_jsonb(OLD) - 'activated_at')
            THEN
                RAISE EXCEPTION 'The support bootstrap approval and roster are immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute(
        "CREATE TRIGGER support_bootstrap_finalize BEFORE UPDATE ON support_bootstrap "
        "FOR EACH ROW EXECUTE FUNCTION finalize_support_bootstrap()"
    )
    op.alter_column("support_registrations", "custody_action_id", nullable=True)
    op.add_column("support_registrations", sa.Column("bootstrap_operator_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_support_registration_bootstrap_operator",
        "support_registrations",
        "support_operators",
        ["bootstrap_operator_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "invitation_authority",
        "support_registrations",
        "(custody_action_id IS NULL) <> (bootstrap_operator_id IS NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve the first-custodian enrollment and its audit history.")
