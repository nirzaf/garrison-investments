"""Persist proof-bound, one-use receipts for redacted support evidence."""

import sqlalchemy as sa

from alembic import op

revision = "202605310091"
down_revision = "202605310090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_evidence_exports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Uuid(),
            sa.ForeignKey("support_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requester_id",
            sa.Uuid(),
            sa.ForeignKey("support_operators.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requester_session_id",
            sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id", sa.Uuid(), sa.ForeignKey("support_operators.id", ondelete="RESTRICT")
        ),
        sa.Column("reviewer_epoch", sa.BigInteger()),
        sa.Column("reason", sa.String(24), nullable=False),
        sa.Column("source_request_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("row_limit", sa.Integer(), nullable=False),
        sa.Column("filter_status_code", sa.Integer()),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("downloaded_at", sa.DateTime(timezone=True)),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("review_request_id", sa.String(64)),
        sa.Column("download_request_id", sa.String(64)),
        sa.CheckConstraint("row_count BETWEEN 0 AND 10000", name="row_count"),
        sa.CheckConstraint(
            "row_limit BETWEEN 1 AND 10000 AND row_count <= row_limit", name="row_limit"
        ),
        sa.CheckConstraint("reason IN ('incident_review', 'audit_review')", name="reason"),
        sa.CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id <> requester_id", name="independent"
        ),
        sa.CheckConstraint(
            "(approved_at IS NULL) = (reviewer_id IS NULL) AND "
            "(approved_at IS NULL) = (reviewer_epoch IS NULL) AND "
            "(approved_at IS NULL) = (review_request_id IS NULL) AND "
            "(downloaded_at IS NULL) = (download_request_id IS NULL) AND "
            "(downloaded_at IS NULL OR approved_at IS NOT NULL)",
            name="decision",
        ),
    )
    op.create_table(
        "support_evidence_proofs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "action_id",
            sa.Uuid(),
            sa.ForeignKey("support_evidence_exports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("support_sessions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("stage", sa.String(8), nullable=False),
        sa.Column("challenge", sa.LargeBinary(32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("stage IN ('review', 'download')", name="stage"),
    )
    op.execute("""
        CREATE FUNCTION preserve_support_evidence_receipt() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            decision_fields text[] := ARRAY[
                'reviewer_id', 'reviewer_epoch', 'approved_at', 'review_request_id',
                'downloaded_at', 'download_request_id'
            ];
        BEGIN
            IF (to_jsonb(NEW) - decision_fields) IS DISTINCT FROM
               (to_jsonb(OLD) - decision_fields) OR
               (OLD.approved_at IS NOT NULL AND
                ROW(NEW.reviewer_id, NEW.reviewer_epoch, NEW.approved_at, NEW.review_request_id)
                IS DISTINCT FROM
                ROW(OLD.reviewer_id, OLD.reviewer_epoch, OLD.approved_at, OLD.review_request_id)) OR
               (OLD.downloaded_at IS NOT NULL AND
                ROW(NEW.downloaded_at, NEW.download_request_id)
                IS DISTINCT FROM ROW(OLD.downloaded_at, OLD.download_request_id))
            THEN
                RAISE EXCEPTION 'The support evidence receipt has already been recorded';
            END IF;
            RETURN NEW;
        END;
        $$;
    """)
    op.execute(
        "CREATE TRIGGER preserve_support_evidence_receipt BEFORE UPDATE "
        "ON support_evidence_exports "
        "FOR EACH ROW EXECUTE FUNCTION preserve_support_evidence_receipt()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_append_only BEFORE DELETE ON support_evidence_exports "
        "FOR EACH ROW EXECUTE FUNCTION prevent_support_audit_change()"
    )
    op.execute(
        "CREATE TRIGGER support_audit_no_truncate BEFORE TRUNCATE ON support_evidence_exports "
        "FOR EACH STATEMENT EXECUTE FUNCTION prevent_support_audit_change()"
    )
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_support_evidence_exports_requester_expiry",
            "support_evidence_exports",
            ["requester_id", "expires_at"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_support_evidence_proofs_action_stage",
            "support_evidence_proofs",
            ["action_id", "stage"],
            postgresql_concurrently=True,
        )
    op.drop_constraint(
        op.f("ck_support_operator_grants_capability"), "support_operator_grants", type_="check"
    )
    op.create_check_constraint(
        "capability",
        "support_operator_grants",
        "capability IN ('logs.runtime','operator.manage','cases.manage','health.read',"
        "'directory.read','account.request','logs.audit','simulation.start',"
        "'logs.stream','logs.export')",
    )
    op.drop_constraint(
        op.f("ck_support_custody_actions_bounded_action"), "support_custody_actions", type_="check"
    )
    op.create_check_constraint(
        "bounded_action",
        "support_custody_actions",
        "(kind IN ('suspend','enroll','recover') AND capability IS NULL AND enable IS NULL)"
        " OR (kind = 'grant_change' AND capability IS NOT NULL AND"
        " capability IN ('cases.manage','logs.runtime','health.read','directory.read',"
        "'account.request','logs.audit','simulation.start','logs.stream','logs.export')"
        " AND enable IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Preserve reviewed support evidence export receipts.")
