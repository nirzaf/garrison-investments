"""Permit optional director decisions on versioned material submissions."""

from alembic import op

revision = "202605310107"
down_revision = "202605310106"
branch_labels = None
depends_on = None


def _replace_check(stages: str) -> None:
    op.drop_constraint("material_submission_stage", "approvals", type_="check")
    op.create_check_constraint(
        "material_submission_stage",
        "approvals",
        "submission_revision IS NULL OR "
        f"(request_type = 'material_request' AND step_order IN ({stages}))",
    )


def upgrade() -> None:
    _replace_check("1, 2, 3, 4")


def downgrade() -> None:
    _replace_check("1, 2")
