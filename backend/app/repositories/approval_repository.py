from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, approval: Approval) -> Approval:
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def get_by_id(self, approval_id: UUID, *, for_update: bool = False) -> Approval | None:
        query = select(Approval).where(Approval.id == approval_id, Approval.deleted_at.is_(None))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(query)

    async def get_open_for_request(self, request_type: str, request_id: UUID) -> Approval | None:
        return await self.session.scalar(
            select(Approval).where(
                Approval.request_type == request_type,
                Approval.request_id == request_id,
                Approval.status.in_(["pending", "delegated", "escalated"]),
                Approval.deleted_at.is_(None),
            )
        )

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        box: str,
        status: str | None,
        limit: int,
        offset: int,
        include_all_inbox: bool = False,
    ) -> tuple[list[Approval], int]:
        query: Select[Approval] = select(Approval).where(Approval.deleted_at.is_(None))
        if box == "outbox":
            query = query.where(Approval.submitter_id == user_id)
        elif not include_all_inbox:
            query = query.where(
                or_(Approval.approver_id == user_id, Approval.delegated_to_id == user_id)
            )
        if status:
            query = query.where(Approval.status == status)
        total_query = select(func.count()).select_from(
            query.with_only_columns(Approval.id).subquery()
        )
        total = int(await self.session.scalar(total_query) or 0)
        approvals = list(
            (
                await self.session.scalars(
                    query.order_by(Approval.submitted_at.desc()).limit(limit).offset(offset)
                )
            ).all()
        )
        return approvals, total

    async def list_due_for_reminder(self, now: datetime) -> list[Approval]:
        return list(
            (
                await self.session.scalars(
                    select(Approval).where(
                        Approval.status.in_(["pending", "delegated"]),
                        Approval.reminded_at.is_(None),
                        Approval.due_at <= now,
                        Approval.deleted_at.is_(None),
                    )
                )
            ).all()
        )

    async def list_due_for_escalation(self, now: datetime) -> list[Approval]:
        return list(
            (
                await self.session.scalars(
                    select(Approval).where(
                        Approval.status.in_(["pending", "delegated"]),
                        Approval.escalated_at.is_(None),
                        Approval.due_at <= now,
                        Approval.deleted_at.is_(None),
                    )
                )
            ).all()
        )
