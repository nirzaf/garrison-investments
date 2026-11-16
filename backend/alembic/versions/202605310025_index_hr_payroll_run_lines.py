"""Index frozen snapshot and payslip reads by run and employee."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310025"
down_revision: str | None = "202605310024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "ix_hr_payroll_lines_run_employee"


def upgrade() -> None:
    context = op.get_context()
    with context.autocommit_block():
        if not context.as_sql:
            existing = (
                op.get_bind()
                .execute(
                    sa.text(
                        """
                    SELECT idx.indisvalid,
                           pg_get_indexdef(idx.indexrelid) = format(
                               'CREATE INDEX %I ON %I.%I USING btree (payroll_run_id, employee_id)',
                               candidate.relname, namespace.nspname, target.relname
                           ) AS matches
                    FROM pg_class AS candidate
                    LEFT JOIN pg_index AS idx
                        ON idx.indexrelid = candidate.oid
                        AND idx.indrelid = to_regclass('hr_payroll_lines')
                    LEFT JOIN pg_class AS target ON target.oid = idx.indrelid
                    LEFT JOIN pg_namespace AS namespace ON namespace.oid = target.relnamespace
                    WHERE candidate.oid = to_regclass(:index_name)
                    """
                    ),
                    {"index_name": INDEX_NAME},
                )
                .one_or_none()
            )
            if existing is not None:
                if not existing.matches or not existing.indisvalid:
                    raise RuntimeError(
                        "Existing payroll read index is invalid or has an unexpected definition."
                    )
                # CREATE INDEX CONCURRENTLY may have committed before Alembic stamped the revision.
                return
        op.create_index(
            INDEX_NAME,
            "hr_payroll_lines",
            ["payroll_run_id", "employee_id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Protect the index before entering the same autocommit boundary that drops it.
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM hr_payslip_publications)")):
        raise RuntimeError("Cannot downgrade payroll schema after payslip publication.")
    with op.get_context().autocommit_block():
        op.drop_index(
            INDEX_NAME,
            table_name="hr_payroll_lines",
            postgresql_concurrently=True,
        )
