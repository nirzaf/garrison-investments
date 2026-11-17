"""Bind CLI support sessions to one browser-approved passkey challenge."""

import sqlalchemy as sa

from alembic import op

revision = "202605310087"
down_revision = "202605310086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("cli_token_hash", "cli_csrf_hash", "cli_code_hash"):
        op.add_column("support_login_challenges", sa.Column(name, sa.String(64)))
    op.create_check_constraint(
        "cli_binding",
        "support_login_challenges",
        "(cli_token_hash IS NULL) = (cli_csrf_hash IS NULL)"
        " AND (cli_token_hash IS NULL) = (cli_code_hash IS NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve support CLI login challenge evidence.")
