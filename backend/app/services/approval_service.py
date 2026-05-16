from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.user_repository import UserRepository
from app.schemas.approvals import ApprovalCreateRequest
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import ROLE_ADMIN, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER
from app.utils.security import utc_now

APPROVAL_PENDING_STATUSES = {"pending", "delegated", "escalated"}


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.approvals = ApprovalRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def create_approval(self, payload: ApprovalCreateRequest, actor: User) -> Approval:
        existing = await self.approvals.get_open_for_request(
            payload.request_type, payload.request_id
        )
        if existing:
            raise AppException(
                "An approval workflow is already pending for this request.",
                status_code=409,
                error_code="APPROVAL_ALREADY_PENDING",
            )
        approver = await self._resolve_approver(payload)
        escalation_user = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
        now = utc_now()
        approval = await self.approvals.add(
            Approval(
                request_type=payload.request_type,
                request_id=payload.request_id,
                project_id=payload.project_id,
                submitter_id=actor.id,
                approver_id=approver.id,
                escalation_user_id=escalation_user.id if escalation_user else None,
                status="pending",
                amount=payload.amount,
                currency=payload.currency,
                title=payload.title,
                submitter_comments=payload.comments,
                submitted_at=now,
                due_at=now + timedelta(hours=24),
            )
        )
        await self.notifications.create(
            user_id=approver.id,
            title="Approval pending",
            body=f"{payload.title} is waiting for your approval.",
            notification_type="approval",
            reference_type="approvals",
            reference_id=approval.id,
        )
        await self.audit.record(
            action="approvals.created",
            user_id=actor.id,
            entity_type=payload.request_type,
            entity_id=payload.request_id,
            new_values={
                "approval_id": str(approval.id),
                "approver_id": str(approver.id),
                "amount": str(payload.amount) if payload.amount is not None else None,
            },
        )
        await self.session.commit()
        return approval

    async def list_for_user(
        self,
        *,
        actor: User,
        box: str,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Approval], int]:
        if box not in {"inbox", "outbox"}:
            raise AppException("Invalid approval box.", status_code=422, error_code="INVALID_BOX")
        return await self.approvals.list_for_user(
            user_id=actor.id,
            box=box,
            status=status,
            limit=limit,
            offset=offset,
        )

    async def get_for_actor(self, approval_id: UUID, actor: User) -> Approval:
        approval = await self._get(approval_id)
        if not self._can_view(approval, actor):
            raise AppException(
                "You do not have access to this approval.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        return approval

    async def approve(self, approval_id: UUID, actor: User, comments: str | None) -> Approval:
        approval = await self._get_actionable(approval_id, actor)
        approval.status = "approved"
        approval.decision_comments = comments
        approval.decided_at = utc_now()
        await self._notify_submitter(
            approval, "Approval completed", f"{approval.title} was approved."
        )
        await self.audit.record(
            action="approvals.approved",
            user_id=actor.id,
            entity_type=approval.request_type,
            entity_id=approval.request_id,
            new_values={"approval_id": str(approval.id), "comments": comments},
        )
        await self.session.commit()
        return approval

    async def reject(self, approval_id: UUID, actor: User, comments: str | None) -> Approval:
        if not comments or not comments.strip():
            raise AppException(
                "Rejection reason is required.",
                status_code=422,
                error_code="REJECTION_REASON_REQUIRED",
            )
        approval = await self._get_actionable(approval_id, actor)
        approval.status = "rejected"
        approval.decision_comments = comments.strip()
        approval.decided_at = utc_now()
        await self._notify_submitter(
            approval, "Approval rejected", f"{approval.title} was rejected."
        )
        await self.audit.record(
            action="approvals.rejected",
            user_id=actor.id,
            entity_type=approval.request_type,
            entity_id=approval.request_id,
            new_values={"approval_id": str(approval.id), "comments": approval.decision_comments},
        )
        await self.session.commit()
        return approval

    async def delegate(
        self,
        approval_id: UUID,
        actor: User,
        delegated_to_id: UUID,
        reason: str,
    ) -> Approval:
        approval = await self._get_actionable(approval_id, actor)
        delegated_to = await self.users.get_by_id(delegated_to_id)
        if not delegated_to or not delegated_to.is_active:
            raise NotFoundException("Delegated approver")
        previous_delegate = approval.delegated_to_id
        approval.status = "delegated"
        approval.delegated_to_id = delegated_to.id
        approval.delegation_reason = reason
        await self.notifications.create(
            user_id=delegated_to.id,
            title="Approval delegated",
            body=f"{approval.title} was delegated to you.",
            notification_type="approval",
            reference_type="approvals",
            reference_id=approval.id,
        )
        await self.audit.record(
            action="approvals.delegated",
            user_id=actor.id,
            entity_type=approval.request_type,
            entity_id=approval.request_id,
            old_values={"delegated_to_id": str(previous_delegate) if previous_delegate else None},
            new_values={
                "approval_id": str(approval.id),
                "delegated_to_id": str(delegated_to.id),
                "reason": reason,
            },
        )
        await self.session.commit()
        return approval

    async def override(
        self,
        approval_id: UUID,
        actor: User,
        decision: str,
        reason: str,
    ) -> Approval:
        if actor.role != ROLE_ADMIN:
            raise AppException(
                "Only Admin can override approvals.",
                status_code=403,
                error_code="APPROVAL_OVERRIDE_FORBIDDEN",
            )
        approval = await self._get(approval_id)
        if approval.status not in APPROVAL_PENDING_STATUSES:
            raise AppException(
                "Only pending approvals can be overridden.",
                status_code=409,
                error_code="APPROVAL_FINAL",
            )
        approval.status = f"override_{decision}"
        approval.override_reason = reason
        approval.decided_at = utc_now()
        await self._notify_submitter(
            approval,
            "Approval overridden",
            f"{approval.title} was {decision} by admin override.",
        )
        await self.audit.record(
            action="approvals.overridden",
            user_id=actor.id,
            entity_type=approval.request_type,
            entity_id=approval.request_id,
            old_values={"approver_id": str(approval.approver_id) if approval.approver_id else None},
            new_values={"approval_id": str(approval.id), "decision": decision, "reason": reason},
        )
        await self.session.commit()
        return approval

    async def send_reminders_and_escalations(self) -> tuple[int, int]:
        now = utc_now()
        reminded = 0
        escalated = 0
        for approval in await self.approvals.list_due_for_reminder(now):
            recipient_id = approval.delegated_to_id or approval.approver_id
            if recipient_id:
                await self.notifications.create(
                    user_id=recipient_id,
                    title="Approval reminder",
                    body=f"{approval.title} is still waiting for approval.",
                    notification_type="approval",
                    reference_type="approvals",
                    reference_id=approval.id,
                )
                approval.reminded_at = now
                reminded += 1
        escalation_cutoff = now - timedelta(hours=24)
        for approval in await self.approvals.list_due_for_escalation(escalation_cutoff):
            if approval.escalation_user_id:
                await self.notifications.create(
                    user_id=approval.escalation_user_id,
                    title="Approval escalated",
                    body=f"{approval.title} has been pending for more than 48 hours.",
                    notification_type="approval",
                    reference_type="approvals",
                    reference_id=approval.id,
                )
                approval.status = "escalated"
                approval.escalated_at = now
                escalated += 1
        await self.session.commit()
        return reminded, escalated

    async def _get(self, approval_id: UUID) -> Approval:
        approval = await self.approvals.get_by_id(approval_id)
        if not approval:
            raise NotFoundException("Approval")
        return approval

    async def _get_actionable(self, approval_id: UUID, actor: User) -> Approval:
        approval = await self._get(approval_id)
        if approval.status not in APPROVAL_PENDING_STATUSES:
            raise AppException(
                "Approval is already final.",
                status_code=409,
                error_code="APPROVAL_FINAL",
            )
        if not self._can_act(approval, actor):
            raise AppException(
                "You cannot act on this approval.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        return approval

    async def _resolve_approver(self, payload: ApprovalCreateRequest) -> User:
        if (
            payload.request_type == "material_request"
            and payload.amount is not None
            and payload.amount > Decimal("1000.00")
        ):
            approver = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
            if approver:
                return approver
        if payload.project_id:
            project_manager = await self.session.scalar(
                select(User)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(
                    ProjectMember.project_id == payload.project_id,
                    ProjectMember.deleted_at.is_(None),
                    User.role == ROLE_PROJECT_MANAGER,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
                .order_by(User.full_name.asc())
            )
            if project_manager:
                return project_manager
        approver = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
        if approver:
            return approver
        admin = await self._first_active_role_user(ROLE_ADMIN)
        if admin:
            return admin
        raise AppException(
            "No active approver is configured.",
            status_code=409,
            error_code="APPROVER_NOT_CONFIGURED",
        )

    async def _first_active_role_user(self, role: str) -> User | None:
        return await self.session.scalar(
            select(User)
            .where(User.role == role, User.is_active.is_(True), User.deleted_at.is_(None))
            .order_by(User.full_name.asc())
        )

    def _can_view(self, approval: Approval, actor: User) -> bool:
        return actor.role == ROLE_ADMIN or actor.id in {
            approval.submitter_id,
            approval.approver_id,
            approval.delegated_to_id,
            approval.escalation_user_id,
        }

    def _can_act(self, approval: Approval, actor: User) -> bool:
        return actor.id in {approval.approver_id, approval.delegated_to_id}

    async def _notify_submitter(self, approval: Approval, title: str, body: str) -> None:
        if approval.submitter_id:
            await self.notifications.create(
                user_id=approval.submitter_id,
                title=title,
                body=body,
                notification_type="approval",
                reference_type="approvals",
                reference_id=approval.id,
            )
