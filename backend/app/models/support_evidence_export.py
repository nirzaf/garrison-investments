from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportEvidenceExport(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_evidence_exports"
    __table_args__ = (
        Index("ix_support_evidence_exports_requester_expiry", "requester_id", "expires_at"),
        CheckConstraint("row_count BETWEEN 0 AND 10000", name="row_count"),
        CheckConstraint(
            "row_limit BETWEEN 1 AND 10000 AND row_count <= row_limit", name="row_limit"
        ),
        CheckConstraint("reason IN ('incident_review', 'audit_review')", name="reason"),
        CheckConstraint("reviewer_id IS NULL OR reviewer_id <> requester_id", name="independent"),
        CheckConstraint(
            (
                "(approved_at IS NULL) = (review_request_id IS NULL) AND (downloaded_at IS "
                "NULL) = (download_request_id IS NULL) AND (downloaded_at IS NULL OR "
                "approved_at IS NOT NULL) AND ((authorization_mode = 'paired' AND "
                "(approved_at IS NULL) = (reviewer_id IS NULL) AND (approved_at IS NULL) = "
                "(reviewer_epoch IS NULL)) OR (authorization_mode = 'single_owner' AND "
                "reviewer_id IS NULL AND reviewer_epoch IS NULL))"
            ),
            name="decision",
        ),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("support_cases.id", ondelete="RESTRICT"))
    requester_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    requester_session_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_sessions.id", ondelete="RESTRICT")
    )
    authorization_mode: Mapped[str] = mapped_column(String(20), server_default="paired")
    reviewer_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("support_operators.id", ondelete="RESTRICT")
    )
    reviewer_epoch: Mapped[int | None] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(String(24))
    source_request_id: Mapped[str] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    row_limit: Mapped[int]
    filter_status_code: Mapped[int | None]
    row_count: Mapped[int]
    truncated: Mapped[bool] = mapped_column(Boolean)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[str] = mapped_column(String(64))
    review_request_id: Mapped[str | None] = mapped_column(String(64))
    download_request_id: Mapped[str | None] = mapped_column(String(64))


class SupportEvidenceProof(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_evidence_proofs"
    __table_args__ = (
        CheckConstraint("stage IN ('review', 'download')", name="stage"),
        Index("ix_support_evidence_proofs_action_stage", "action_id", "stage"),
    )

    action_id: Mapped[UUID] = mapped_column(
        ForeignKey("support_evidence_exports.id", ondelete="RESTRICT")
    )
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    stage: Mapped[str] = mapped_column(String(8))
    challenge: Mapped[bytes] = mapped_column(LargeBinary(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
