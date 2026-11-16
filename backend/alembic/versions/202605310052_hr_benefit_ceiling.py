"""Configure and independently approve reimbursement ceilings."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310052"
down_revision: str | None = "202605310051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hr_benefit_types", sa.Column("reimbursement_ceiling", sa.Numeric(15, 2)))
    op.add_column("hr_benefit_types", sa.Column("reimbursement_currency", sa.String(3)))
    op.add_column("hr_benefit_types", sa.Column("proposed_by_id", sa.Uuid()))
    op.add_column("hr_benefit_types", sa.Column("approved_by_id", sa.Uuid()))
    op.add_column("hr_benefit_types", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.add_column("hr_reimbursement_claims", sa.Column("benefit_assignment_id", sa.Uuid()))
    for name, source, target, column, ondelete in (
        (
            "fk_hr_benefit_policy_proposer",
            "hr_benefit_types",
            "users",
            "proposed_by_id",
            "SET NULL",
        ),
        (
            "fk_hr_benefit_policy_approver",
            "hr_benefit_types",
            "users",
            "approved_by_id",
            "SET NULL",
        ),
        (
            "fk_hr_claim_benefit_assignment",
            "hr_reimbursement_claims",
            "hr_employee_benefits",
            "benefit_assignment_id",
            "RESTRICT",
        ),
    ):
        op.create_foreign_key(
            name, source, target, [column], ["id"], ondelete=ondelete, postgresql_not_valid=True
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM hr_benefit_types "
            "WHERE reimbursement_ceiling IS NOT NULL) OR "
            "EXISTS (SELECT 1 FROM hr_reimbursement_claims WHERE benefit_assignment_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("Cannot discard retained reimbursement policies and coverage.")
    op.drop_constraint(
        "fk_hr_claim_benefit_assignment", "hr_reimbursement_claims", type_="foreignkey"
    )
    op.drop_column("hr_reimbursement_claims", "benefit_assignment_id")
    op.drop_constraint("fk_hr_benefit_policy_approver", "hr_benefit_types", type_="foreignkey")
    op.drop_constraint("fk_hr_benefit_policy_proposer", "hr_benefit_types", type_="foreignkey")
    for column in (
        "approved_at",
        "approved_by_id",
        "proposed_by_id",
        "reimbursement_currency",
        "reimbursement_ceiling",
    ):
        op.drop_column("hr_benefit_types", column)
