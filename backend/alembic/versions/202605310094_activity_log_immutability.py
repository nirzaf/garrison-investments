"""Protect activity_log core event records against unauthorized mutation, deletion, or truncate."""

from alembic import op

revision = "202605310094"
down_revision = "202605310093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prevent_activity_log_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'Business audit ledger is append-only and cannot be truncated';
            END IF;

            IF TG_OP = 'DELETE' THEN
                IF current_setting('garrison.audit_retention_purge', true) = 'allow'
                    AND OLD.storage_tier = 'archive'
                    AND OLD.retention_until IS NOT NULL
                    AND OLD.deleted_at IS NULL
                THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'Business audit ledger deletions require an approved archive purge';
            END IF;

            IF TG_OP = 'UPDATE' THEN
                IF NEW.id IS DISTINCT FROM OLD.id
                    OR NEW.user_id IS DISTINCT FROM OLD.user_id
                    OR NEW.event_type IS DISTINCT FROM OLD.event_type
                    OR NEW.severity IS DISTINCT FROM OLD.severity
                    OR NEW.action IS DISTINCT FROM OLD.action
                    OR NEW.entity_type IS DISTINCT FROM OLD.entity_type
                    OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
                    OR NEW.request_id IS DISTINCT FROM OLD.request_id
                    OR NEW.session_id IS DISTINCT FROM OLD.session_id
                    OR NEW.ip_address IS DISTINCT FROM OLD.ip_address
                    OR NEW.endpoint IS DISTINCT FROM OLD.endpoint
                    OR NEW.http_method IS DISTINCT FROM OLD.http_method
                    OR NEW.status_code IS DISTINCT FROM OLD.status_code
                    OR NEW.source_service IS DISTINCT FROM OLD.source_service
                    OR NEW.instance_id IS DISTINCT FROM OLD.instance_id
                    OR NEW.user_agent IS DISTINCT FROM OLD.user_agent
                    OR NEW.comments IS DISTINCT FROM OLD.comments
                    OR NEW.context_payload IS DISTINCT FROM OLD.context_payload
                    OR NEW.old_values IS DISTINCT FROM OLD.old_values
                    OR NEW.new_values IS DISTINCT FROM OLD.new_values
                    OR NEW.created_at IS DISTINCT FROM OLD.created_at
                    OR NEW.deleted_at IS DISTINCT FROM OLD.deleted_at
                THEN
                    RAISE EXCEPTION 'Business audit ledger event fields are immutable';
                END IF;

                IF NOT (
                    NEW.storage_tier = OLD.storage_tier
                    OR (OLD.storage_tier = 'hot' AND NEW.storage_tier = 'archive')
                ) THEN
                    RAISE EXCEPTION 'Invalid audit storage tier transition';
                END IF;

                IF OLD.storage_tier = 'hot'
                    AND NEW.storage_tier = 'archive'
                    AND NEW.archived_at IS NULL
                THEN
                    RAISE EXCEPTION 'Archived audit rows require archived_at';
                END IF;

                IF OLD.archived_at IS NOT NULL
                    AND NEW.archived_at IS DISTINCT FROM OLD.archived_at
                THEN
                    RAISE EXCEPTION 'Audit archived_at timestamp is immutable once set';
                END IF;

                IF OLD.retention_until IS NOT NULL AND (
                    NEW.retention_until IS NULL OR NEW.retention_until < OLD.retention_until
                ) THEN
                    RAISE EXCEPTION 'Audit retention_until deadline cannot be cleared or shortened';
                END IF;

                RETURN NEW;
            END IF;

            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        "CREATE TRIGGER activity_log_append_only BEFORE UPDATE OR DELETE "
        "ON activity_log FOR EACH ROW EXECUTE FUNCTION prevent_activity_log_mutation()"
    )
    op.execute(
        "CREATE TRIGGER activity_log_no_truncate BEFORE TRUNCATE "
        "ON activity_log FOR EACH STATEMENT EXECUTE FUNCTION prevent_activity_log_mutation()"
    )


def downgrade() -> None:
    raise RuntimeError("Preserve business audit ledger immutability protections.")
