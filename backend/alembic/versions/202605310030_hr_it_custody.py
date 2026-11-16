"""Retain IT equipment handover in a separate clearance area."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310030"
down_revision: str | None = "202605310029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hr_offboarding_custody",
        sa.Column("area", sa.String(16), nullable=False, server_default="store_inventory"),
    )
    op.add_column("hr_offboarding_custody", sa.Column("device_reference", sa.String(100)))
    op.create_check_constraint(
        "hr_custody_area_kind",
        "hr_offboarding_custody",
        "(area = 'store_inventory' AND device_reference IS NULL AND "
        "((kind = 'returned' AND movement_id IS NOT NULL) OR "
        "(kind IN ('cleared', 'waived', 'flagged') AND movement_id IS NULL))) OR "
        "(area = 'it_admin' AND movement_id IS NULL AND "
        "((kind = 'cleared' AND device_reference IS NULL) OR "
        "(kind IN ('returned', 'waived', 'flagged') AND device_reference IS NOT NULL)))",
        postgresql_not_valid=True,
    )
    op.drop_constraint("hr_custody_kind", "hr_offboarding_custody", type_="check")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM hr_offboarding_custody WHERE area = 'it_admin')")
    ):
        raise RuntimeError("Cannot remove retained IT handover evidence.")
    op.create_check_constraint(
        "hr_custody_kind",
        "hr_offboarding_custody",
        "(kind = 'returned' AND movement_id IS NOT NULL) OR "
        "(kind IN ('cleared', 'waived', 'flagged') AND movement_id IS NULL)",
    )
    op.drop_constraint("hr_custody_area_kind", "hr_offboarding_custody", type_="check")
    op.drop_column("hr_offboarding_custody", "device_reference")
    op.drop_column("hr_offboarding_custody", "area")
