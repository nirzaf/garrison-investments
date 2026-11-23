"""Provision the People & Access read grant for an enrolled single owner."""

from alembic import op

revision = "202605310100"
down_revision = "202605310099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        WITH granted AS (
            INSERT INTO support_operator_grants (operator_id, capability)
            SELECT owner.id, 'company.directory.read'
            FROM support_bootstrap AS bootstrap
            JOIN support_operators AS owner ON owner.id = bootstrap.first_id
            JOIN support_operator_grants AS custody
              ON custody.operator_id = owner.id AND custody.capability = 'operator.manage'
            WHERE bootstrap.id = 1
              AND bootstrap.custody_mode = 'single_owner'
              AND bootstrap.second_id IS NULL
              AND bootstrap.activated_at IS NOT NULL
              AND owner.status = 'active'
            ON CONFLICT (operator_id, capability) DO NOTHING
            RETURNING operator_id
        ), advanced AS (
            UPDATE support_operators AS owner
            SET grant_epoch = owner.grant_epoch + 1
            FROM granted
            WHERE owner.id = granted.operator_id
            RETURNING owner.id, owner.grant_epoch
        ), revoked AS (
            UPDATE support_sessions AS session
            SET revoked_at = now()
            FROM advanced
            WHERE session.operator_id = advanced.id AND session.revoked_at IS NULL
        )
        INSERT INTO activity_log
            (action, event_type, entity_type, entity_id, request_id, new_values)
        SELECT 'support.company_directory_grant_backfilled', 'audit', 'support_operator',
               id, 'migration-202605310100',
               jsonb_build_object(
                   'capability', 'company.directory.read', 'grant_epoch', grant_epoch
               )
        FROM advanced
        """
    )


def downgrade() -> None:
    raise RuntimeError("Preserve the audited grant and revoked sessions on application rollback.")
