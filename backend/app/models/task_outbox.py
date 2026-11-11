from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaskOutbox(Base):
    __tablename__ = "task_outbox"
    __table_args__ = (
        Index(
            "ix_task_outbox_pending",
            "created_at",
            "id",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()")
    )
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    args_json: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    kwargs_json: Mapped[dict[str, bool]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
