import re
from datetime import timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.models.user_feedback import UserFeedback
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackInboxItem,
    FeedbackInboxPage,
    FeedbackReceipt,
    FeedbackStatus,
    FeedbackStatusChange,
)
from app.services.audit_service import AuditService
from app.services.support_admin_policy import resolve_support_actor_context
from app.utils.exceptions import AppException, NotFoundException
from app.utils.redaction import redact_text
from app.utils.security import utc_now

_DIAGNOSTIC_AREAS = frozenset(
    {
        "analytics",
        "approvals",
        "dashboard",
        "documents",
        "finance",
        "hr",
        "imports",
        "inventory",
        "notifications",
        "photos",
        "projects",
        "reports",
        "supervisor-updates",
        "suppliers",
        "users",
    }
)
_HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"})
_LINK = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.DOTALL
)


def _clean_feedback(value: str, max_length: int) -> str:
    value = _LINK.sub("[link removed]", value.replace("\x00", ""))
    value = _PRIVATE_KEY.sub("[private key removed]", value)
    return redact_text(value)[:max_length]


class FeedbackService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def submit(self, actor: User, payload: FeedbackCreate) -> FeedbackReceipt:
        # Serialize the per-reporter submission limit and idempotency check.
        reporter_id = actor.id
        locked = await self.session.scalar(
            select(User.id)
            .where(
                User.id == reporter_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.access_revision == actor.access_revision,
            )
            .with_for_update()
        )
        if locked is None:
            raise AppException(
                "Authentication required.", status_code=401, error_code="AUTH_REQUIRED"
            )

        fingerprint = sha256(payload.model_dump_json().encode()).hexdigest()
        feedback = await self.session.scalar(
            select(UserFeedback).where(
                UserFeedback.reporter_id == reporter_id,
                UserFeedback.submission_id == payload.submission_id,
            )
        )
        if feedback is not None:
            if feedback.submission_fingerprint != fingerprint:
                raise AppException(
                    "This submission reference was already used for different feedback.",
                    status_code=409,
                    error_code="FEEDBACK_SUBMISSION_CONFLICT",
                )
        else:
            now = utc_now()
            count = await self.session.scalar(
                select(func.count())
                .select_from(UserFeedback)
                .where(
                    UserFeedback.reporter_id == reporter_id,
                    UserFeedback.created_at >= now - timedelta(hours=1),
                )
            )
            if count is not None and count >= 10:
                raise AppException(
                    "You can submit up to 10 reports per hour. Try again later.",
                    status_code=429,
                    error_code="FEEDBACK_RATE_LIMITED",
                )
            feedback = UserFeedback(
                id=uuid4(),
                reporter_id=reporter_id,
                submission_id=payload.submission_id,
                submission_fingerprint=fingerprint,
                category=payload.category,
                title=_clean_feedback(payload.title, 140),
                description=_clean_feedback(payload.description, 4000),
                diagnostics=await self._diagnostics(reporter_id, payload.request_ids),
            )
            self.session.add(feedback)
            await self.session.flush()
            await AuditService(self.session).record(
                action="feedback.submitted",
                user_id=reporter_id,
                entity_type="user_feedback",
                entity_id=feedback.id,
                context_payload={
                    "category": feedback.category,
                    "diagnostic_count": len(feedback.diagnostics),
                },
            )
        receipt = FeedbackReceipt(
            id=feedback.id,
            created_at=feedback.created_at,
            attached_diagnostics=len(feedback.diagnostics),
        )
        await self.session.commit()
        return receipt

    async def _diagnostics(
        self, reporter_id: UUID, request_ids: list[str]
    ) -> list[dict[str, str | int]]:
        if not request_ids:
            return []
        prefix = get_settings().api_v1_prefix + "/"
        rows = await self.session.execute(
            select(
                ActivityLog.request_id,
                ActivityLog.created_at,
                ActivityLog.endpoint,
                ActivityLog.http_method,
                ActivityLog.status_code,
            )
            .where(
                ActivityLog.request_id.in_(request_ids),
                ActivityLog.user_id == reporter_id,
                ActivityLog.created_at >= utc_now() - timedelta(minutes=30),
                ActivityLog.deleted_at.is_(None),
                ActivityLog.action.in_(("http.request", "http.unhandled_exception")),
                ActivityLog.status_code.between(400, 599),
                ActivityLog.endpoint.startswith(prefix, autoescape=True),
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(16)
        )
        matched: dict[str, dict[str, str | int]] = {}
        for request_id, occurred_at, endpoint, method, code in rows:
            area = endpoint[len(prefix) :].partition("/")[0] if endpoint else ""
            if (
                not request_id
                or code is None
                or area not in _DIAGNOSTIC_AREAS
                or method not in _HTTP_METHODS
            ):
                continue
            matched.setdefault(
                request_id,
                {
                    "request_id": request_id,
                    "occurred_at": occurred_at.isoformat(),
                    "area": area,
                    "method": method,
                    "status_code": code,
                },
            )
        return list(matched.values())[:8]

    async def list_inbox(
        self,
        token: str | None,
        request_id: str,
        *,
        status: FeedbackStatus | None,
        limit: int,
        offset: int,
    ) -> FeedbackInboxPage:
        ctx, _, active = await resolve_support_actor_context(
            self.session, token, request_id=request_id, required_capability="operator.manage"
        )
        query = select(UserFeedback)
        if status is not None:
            query = query.where(UserFeedback.status == status)
        rows = list(
            await self.session.scalars(
                query.order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())
                .limit(limit + 1)
                .offset(offset)
            )
        )
        result = FeedbackInboxPage(
            items=[FeedbackInboxItem.model_validate(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )
        active.last_seen_at = utc_now()
        await AuditService(self.session).record(
            action="feedback.inbox_read",
            entity_type="user_feedback",
            context_payload={
                "operator_id": str(ctx.operator_id),
                "item_count": len(result.items),
                "status": status,
            },
        )
        await self.session.commit()
        return result

    async def change_status(
        self,
        token: str | None,
        csrf: str | None,
        request_id: str,
        feedback_id: UUID,
        payload: FeedbackStatusChange,
    ) -> FeedbackInboxItem:
        ctx, _, active = await resolve_support_actor_context(
            self.session,
            token,
            csrf,
            request_id=request_id,
            required_capability="operator.manage",
            require_csrf=True,
        )
        feedback = await self.session.get(UserFeedback, feedback_id, with_for_update=True)
        if feedback is None:
            raise NotFoundException("Feedback")
        if feedback.revision != payload.expected_revision:
            raise AppException(
                "This report changed. Refresh the inbox before updating it.",
                status_code=409,
                error_code="FEEDBACK_STALE_REVISION",
            )
        if feedback.status != payload.status:
            previous_status = feedback.status
            feedback.status = payload.status
            feedback.revision += 1
            feedback.updated_at = utc_now()
            await AuditService(self.session).record(
                action="feedback.status_changed",
                entity_type="user_feedback",
                entity_id=feedback.id,
                context_payload={"operator_id": str(ctx.operator_id)},
                old_values={"status": previous_status},
                new_values={"status": feedback.status, "revision": feedback.revision},
            )
        result = FeedbackInboxItem.model_validate(feedback)
        active.last_seen_at = utc_now()
        await self.session.commit()
        return result
