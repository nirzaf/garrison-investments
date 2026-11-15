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

    async def lock_open_for_request(self, request_type: str, request_id: UUID) -> list[Approval]:
        return list(
            await self.session.scalars(
                select(Approval)
                .where(
                    Approval.request_type == request_type,
                    Approval.request_id == request_id,
                    Approval.status.in_(["pending", "delegated", "escalated"]),
                    Approval.deleted_at.is_(None),
                )
                .order_by(Approval.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        box: str,
        status: str | None,
        open_only: bool = False,
        limit: int,
        offset: int,
        include_all_inbox: bool = False,
        project_ids: list[UUID] | None = None,
        request_types: set[str] | None = None,
    ) -> tuple[list[Approval], int]:
        query: Select[Approval] = select(Approval).where(Approval.deleted_at.is_(None))
        if request_types is not None:
            query = query.where(Approval.request_type.in_(request_types))
        if box == "outbox":
            query = query.where(Approval.submitter_id == user_id)
        elif not include_all_inbox:
            query = query.where(
                or_(
                    Approval.approver_id == user_id,
                    Approval.delegated_to_id == user_id,
                    (Approval.escalation_user_id == user_id) & (Approval.status == "escalated"),
                )
            )
            if project_ids is not None:
                query = query.where(Approval.project_id.in_(project_ids))
        if status:
            query = query.where(Approval.status == status)
        elif open_only:
            query = query.where(Approval.status.in_(["pending", "delegated", "escalated"]))
        total_query = select(func.count()).select_from(
            query.with_only_columns(Approval.id).subquery()
        )
        total = int(await self.session.scalar(total_query) or 0)
        approvals = list(
            (
                await self.session.scalars(
                    query.order_by(Approval.submitted_at.desc(), Approval.id.desc())
                    .limit(limit)
                    .offset(offset)
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
