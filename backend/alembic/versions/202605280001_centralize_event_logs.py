"""centralize event logs

Revision ID: 202605280001
Revises: 202605170002
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605280001"
down_revision: str | None = "202605170002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "activity_log",
        sa.Column("event_type", sa.String(length=32), nullable=False, server_default="audit"),
    )
    op.add_column(
        "activity_log",
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="INFO"),
    )
    op.add_column("activity_log", sa.Column("request_id", sa.String(length=64), nullable=True))
    op.add_column("activity_log", sa.Column("session_id", sa.String(length=128), nullable=True))
    op.add_column("activity_log", sa.Column("endpoint", sa.String(length=255), nullable=True))
    op.add_column("activity_log", sa.Column("http_method", sa.String(length=16), nullable=True))
    op.add_column("activity_log", sa.Column("status_code", sa.Integer(), nullable=True))
    op.add_column("activity_log", sa.Column("source_service", sa.String(length=64), nullable=True))
    op.add_column("activity_log", sa.Column("instance_id", sa.String(length=128), nullable=True))
    op.add_column(
        "activity_log",
        sa.Column("storage_tier", sa.String(length=16), nullable=False, server_default="hot"),
    )
    op.add_column(
        "activity_log", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "activity_log", sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "activity_log", sa.Column("context_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    op.execute(
        """
        UPDATE activity_log
        SET event_type = 'state_change',
            severity = CASE
                WHEN action LIKE 'auth.%failed%' THEN 'ERROR'
                WHEN action LIKE '%.rejected' THEN 'WARNING'
                ELSE 'INFO'
            END,
            endpoint = COALESCE(new_values ->> 'path', endpoint),
            http_method = COALESCE(new_values ->> 'method', http_method),
            status_code = CASE
                WHEN (new_values ->> 'status_code') ~ '^[0-9]+$'
                    THEN (new_values ->> 'status_code')::integer
                ELSE status_code
            END,
            request_id = COALESCE(new_values ->> 'request_id', request_id),
            session_id = COALESCE(new_values ->> 'session_id', session_id),
            storage_tier = 'hot',
            retention_until = created_at + INTERVAL '365 days',
            context_payload = jsonb_strip_nulls(
                jsonb_build_object(
                    'request_id', new_values ->> 'request_id',
                    'session_id', new_values ->> 'session_id',
                    'endpoint', new_values ->> 'path',
                    'method', new_values ->> 'method'
                )
            )
        """
    )

    op.create_index("ix_activity_log_event_type", "activity_log", ["event_type"], unique=False)
    op.create_index("ix_activity_log_severity", "activity_log", ["severity"], unique=False)
    op.create_index("ix_activity_log_request_id", "activity_log", ["request_id"], unique=False)
    op.create_index("ix_activity_log_session_id", "activity_log", ["session_id"], unique=False)
    op.create_index("ix_activity_log_endpoint", "activity_log", ["endpoint"], unique=False)
    op.create_index(
        "ix_activity_log_storage_tier", "activity_log", ["storage_tier"], unique=False
    )
    op.create_index(
        "ix_activity_log_source_service", "activity_log", ["source_service"], unique=False
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION activity_log_search_vector(
            event_type text, severity text, action text, entity_type text,
            endpoint text, comments text, context_payload text,
            old_values text, new_values text
        ) RETURNS tsvector LANGUAGE sql IMMUTABLE AS $$
            SELECT to_tsvector(
                'simple',
                concat_ws(
                    ' ',
                    coalesce(event_type, ''),
                    coalesce(severity, ''),
                    coalesce(action, ''),
                    coalesce(entity_type, ''),
                    coalesce(endpoint, ''),
                    coalesce(comments, ''),
                    coalesce(context_payload, ''),
                    coalesce(old_values, ''),
                    coalesce(new_values, '')
                )
            )
        $$
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_activity_log_search
        ON activity_log
        USING gin (
            activity_log_search_vector(
                event_type, severity, action, entity_type,
                endpoint, comments, context_payload::text,
                old_values::text, new_values::text
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_activity_log_search")
    op.execute("DROP FUNCTION IF EXISTS activity_log_search_vector")
    op.drop_index("ix_activity_log_source_service", table_name="activity_log")
    op.drop_index("ix_activity_log_storage_tier", table_name="activity_log")
    op.drop_index("ix_activity_log_endpoint", table_name="activity_log")
    op.drop_index("ix_activity_log_session_id", table_name="activity_log")
    op.drop_index("ix_activity_log_request_id", table_name="activity_log")
    op.drop_index("ix_activity_log_severity", table_name="activity_log")
    op.drop_index("ix_activity_log_event_type", table_name="activity_log")
    op.drop_column("activity_log", "context_payload")
    op.drop_column("activity_log", "retention_until")
    op.drop_column("activity_log", "archived_at")
    op.drop_column("activity_log", "storage_tier")
    op.drop_column("activity_log", "instance_id")
    op.drop_column("activity_log", "source_service")
    op.drop_column("activity_log", "status_code")
    op.drop_column("activity_log", "http_method")
    op.drop_column("activity_log", "endpoint")
    op.drop_column("activity_log", "session_id")
    op.drop_column("activity_log", "request_id")
    op.drop_column("activity_log", "severity")
    op.drop_column("activity_log", "event_type")
