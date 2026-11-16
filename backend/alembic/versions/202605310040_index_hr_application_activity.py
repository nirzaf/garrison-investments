"""Index the application stage history without blocking audit writers."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "202605310040"
down_revision: str | None = "202605310039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ix_activity_log_hr_application"


def upgrade() -> None:
    context = op.get_context()
    with context.autocommit_block():
        if not context.as_sql:
            existing = (
                op.get_bind()
                .execute(
                    sa.text(
                        """
                    SELECT idx.indisvalid, pg_get_indexdef(idx.indexrelid) = format(
                        'CREATE INDEX %I ON %I.%I USING btree '
                        '(entity_id, created_at DESC, id DESC) '
                        'WHERE (((entity_type)::text = %L::text) AND (deleted_at IS NULL))',
                        candidate.relname, namespace.nspname, target.relname, 'hr_applications'
                    ) AS matches
                    FROM pg_class AS candidate
                    LEFT JOIN pg_index AS idx
                        ON idx.indexrelid = candidate.oid
                        AND idx.indrelid = to_regclass('activity_log')
                    LEFT JOIN pg_class AS target ON target.oid = idx.indrelid
                    LEFT JOIN pg_namespace AS namespace ON namespace.oid = target.relnamespace
                    WHERE candidate.oid = to_regclass(:index)
                    """
                    ),
                    {"index": INDEX},
                )
                .one_or_none()
            )
            if existing is not None:
                if not existing.indisvalid or not existing.matches:
                    raise RuntimeError(
                        "Application activity index is invalid or has an unexpected definition."
                    )
                return
        op.create_index(
            INDEX,
            "activity_log",
            ["entity_id", sa.text("created_at DESC"), sa.text("id DESC")],
            postgresql_where=sa.text("entity_type = 'hr_applications' AND deleted_at IS NULL"),
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(INDEX, table_name="activity_log", postgresql_concurrently=True)
