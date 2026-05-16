from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        action: str,
        user_id: UUID | None = None,
        entity_type: str | None = None,
        entity_id: UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        comments: str | None = None,
        old_values: dict | None = None,
        new_values: dict | None = None,
    ) -> None:
        self.session.add(
            ActivityLog(
                user_id=user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                ip_address=ip_address,
                user_agent=user_agent,
                comments=comments,
                old_values=old_values,
                new_values=new_values,
            )
        )
