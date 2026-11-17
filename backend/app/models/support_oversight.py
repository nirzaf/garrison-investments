from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

OVERSIGHT_CAPABILITIES: tuple[str, ...] = (
    "overview.company.read",
    "overview.projects.read",
    "overview.workforce.read",
    "overview.inventory.read",
    "overview.suppliers.read",
    "overview.documents.read",
    "overview.finance.read",
    "overview.approvals.read",
    "jobs.read",
    "backups.read",
    "config.read",
    "incidents.read",
)

EXISTING_NON_BOOTSTRAP_CAPABILITIES: tuple[str, ...] = (
    "cases.manage",
    "logs.runtime",
    "logs.stream",
    "logs.export",
    "health.read",
    "directory.read",
    "account.request",
    "logs.audit",
    "simulation.start",
)

ALL_GRANTABLE_CAPABILITIES: tuple[str, ...] = (
    *EXISTING_NON_BOOTSTRAP_CAPABILITIES,
    *OVERSIGHT_CAPABILITIES,
)

ALL_SUPPORT_CAPABILITIES: tuple[str, ...] = ("operator.manage", *ALL_GRANTABLE_CAPABILITIES)

OVERSIGHT_SURFACES: tuple[str, ...] = (
    "overview_company",
    "overview_projects",
    "overview_workforce",
    "overview_inventory",
    "overview_suppliers",
    "overview_documents",
    "overview_finance",
    "overview_approvals",
    "jobs",
    "backups",
    "config",
    "incidents",
    "policy_explain",
)


def sql_quoted_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class SupportOversightEvent(UUIDPrimaryKeyMixin, Base):
    """Append-only disclosure and rate-limit audit for technical oversight reads."""

    __tablename__ = "support_oversight_events"
    __table_args__ = (
        Index("ix_support_oversight_events_operator_occurred", "operator_id", "occurred_at"),
        CheckConstraint(f"surface IN ({sql_quoted_list(OVERSIGHT_SURFACES)})", name="surface"),
        CheckConstraint("action IN ('requested', 'returned')", name="action"),
    )

    operator_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    surface: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(12))
    case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_cases.id", ondelete="RESTRICT")
    )
    request_id: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SupportBackupReceipt(UUIDPrimaryKeyMixin, Base):
    """Append-only attested backup and restore-drill receipt without storage secrets."""

    __tablename__ = "support_backup_receipts"
    __table_args__ = (
        Index("ix_support_backup_receipts_kind_captured", "receipt_kind", "captured_at"),
        CheckConstraint(
            "receipt_kind IN ('scheduled_db_attempt', 'authenticated_backup_set', 'restore_drill')",
            name="receipt_kind",
        ),
        CheckConstraint(
            "target_domain IN ('local_host', 'independent_offhost', 'isolated_restore')",
            name="target_domain",
        ),
        CheckConstraint("outcome IN ('pass', 'fail', 'unknown')", name="outcome"),
    )

    receipt_kind: Mapped[str] = mapped_column(String(32))
    backup_set_id: Mapped[str | None] = mapped_column(String(80))
    manifest_sha256: Mapped[str | None] = mapped_column(String(64))
    target_domain: Mapped[str] = mapped_column(String(32))
    covers_database: Mapped[bool] = mapped_column(Boolean)
    covers_objects: Mapped[bool] = mapped_column(Boolean)
    outcome: Mapped[str] = mapped_column(String(12))
    rpo_minutes: Mapped[int | None] = mapped_column(Integer)
    rto_minutes: Mapped[int | None] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signer_key_id: Mapped[str | None] = mapped_column(String(80))
    recorded_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
