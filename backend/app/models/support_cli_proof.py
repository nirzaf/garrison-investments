from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class SupportCliProof(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "support_cli_proofs"
    __table_args__ = (
        CheckConstraint(
            "(sealed IS NULL) OR (taken_at IS NULL AND length(sealed) BETWEEN 1 AND 32768)",
            name="sealed_state",
        ),
    )

    proof_id: Mapped[UUID] = mapped_column(Uuid(), unique=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("support_sessions.id", ondelete="RESTRICT"))
    pairing_hash: Mapped[str] = mapped_column(String(64))
    public_key: Mapped[str] = mapped_column(String(512))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sealed: Mapped[str | None] = mapped_column(String(32768))
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
