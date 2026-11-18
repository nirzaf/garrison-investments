"""Record the immutable custody mode of initial support enrollment."""

import sqlalchemy as sa

from alembic import op

revision = "202605310095"
down_revision = "202605310094"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_bootstrap",
        sa.Column("custody_mode", sa.String(20), nullable=False, server_default="paired"),
    )
    op.drop_constraint(
        op.f("ck_support_bootstrap_singleton_pair"), "support_bootstrap", type_="check"
    )
    op.alter_column("support_bootstrap", "second_id", nullable=True)
    op.create_check_constraint(
        "singleton_custody",
        "support_bootstrap",
        "id = 1 AND ((custody_mode = 'paired' AND second_id IS NOT NULL "
        "AND first_id <> second_id) OR (custody_mode = 'single_owner' AND second_id IS NULL))",
    )


def downgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM support_bootstrap WHERE custody_mode = 'single_owner') THEN
                RAISE EXCEPTION 'Single-owner custody requires a forward recovery plan';
            END IF;
        END $$;
    """)
    op.drop_constraint(
        op.f("ck_support_bootstrap_singleton_custody"), "support_bootstrap", type_="check"
    )
    op.alter_column("support_bootstrap", "second_id", nullable=False)
    op.drop_column("support_bootstrap", "custody_mode")
    op.create_check_constraint(
        "singleton_pair", "support_bootstrap", "id = 1 AND first_id <> second_id"
    )
