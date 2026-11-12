"""Track material request revisions and replayable command results."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "202605310004"
down_revision = "202605310001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "material_requests", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.add_column("idempotency_records", sa.Column("request_fingerprint", sa.String(64)))
    op.add_column("idempotency_records", sa.Column("response_json", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("idempotency_records", "response_json")
    op.drop_column("idempotency_records", "request_fingerprint")
    op.drop_column("material_requests", "revision")
