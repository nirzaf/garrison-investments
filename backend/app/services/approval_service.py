from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.approval import Approval
from app.models.daily_report import DailyReport
from app.models.document import Document
from app.models.finance import Invoice
from app.models.inventory import MaterialRequest
from app.models.notification import Notification
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.user_repository import UserRepository
from app.schemas.approvals import ApprovalCreateRequest, ApprovalResponse
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.links import (
    append_link,
    approval_inbox_url,
    daily_report_url,
    document_url,
    finance_invoice_url,
    material_request_url,
)
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_REPORTS_APPROVE,
    PERMISSION_REPORTS_SUBMIT,
    REPORT_APPROVER_ROLES,
    ensure_permission,
    has_permission,
    roles_with_permission,
)
from app.utils.security import utc_now

APPROVAL_PENDING_STATUSES = {"pending", "delegated", "escalated"}
ENTITY_BACKED_REQUEST_TYPES = {"material_request", "invoice", "daily_report", "document"}
OPERATING_CURRENCY_APPROVAL_TYPES = {"material_request", "invoice"}
APPROVAL_REMINDER_TITLE = "Approval reminder"
APPROVAL_ESCALATION_TITLE = "Approval escalated"

# Roles that may actually decide each request type. Delegation must not hand decision
# power to someone the owning workflow would reject: `_apply_entity_decision` writes the
# decision directly and never re-runs the downstream service guards.
DELEGATION_ELIGIBLE_ROLES: dict[str, frozenset[str]] = {
    # The role matrix grants read-only finance access, so invoice approval is disabled.
    "invoice": frozenset(),
    "daily_report": frozenset(REPORT_APPROVER_ROLES),
    "document": frozenset(roles_with_permission(PERMISSION_DOCUMENTS_MANAGE)),
    "material_request": frozenset(roles_with_permission(PERMISSION_INVENTORY_MANAGE)),
}


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.approvals = ApprovalRepository(session)
        self.users = UserRepository(session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def create_approval(
        self,
        payload: ApprovalCreateRequest,
        actor: User,
        *,
        commit: bool = True,
        internal: bool = False,
    ) -> Approval:
        if payload.request_type in ENTITY_BACKED_REQUEST_TYPES and not internal:
            raise AppException(
                "This approval type must be created by its owning workflow.",
                status_code=403,
                error_code="APPROVAL_TYPE_FORBIDDEN",
            )
        if payload.request_type in OPERATING_CURRENCY_APPROVAL_TYPES:
            payload = payload.model_copy(update={"currency": get_settings().business_currency})
        existing = await self.approvals.get_open_for_request(
            payload.request_type, payload.request_id
        )
        if existing:
            raise AppException(
                "An approval workflow is already pending for this request.",
                status_code=409,
                error_code="APPROVAL_ALREADY_PENDING",
            )
        approver = await self._resolve_approver(payload, actor)
        escalation_user = await self._first_active_scoped_approver(
            payload.project_id,
            set(DELEGATION_ELIGIBLE_ROLES.get(payload.request_type, frozenset())),
            excluded_user_ids={actor.id, approver.id},
        )
        now = utc_now()
        try:
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
                body=append_link(
                    f"{payload.title} is waiting for your approval.",
                    label="Open approval",
                    url=approval_inbox_url(tab="workflow", approval_id=approval.id),
                ),
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
                    "currency": payload.currency,
                },
            )
            if commit:
                await self.session.commit()
        except IntegrityError as exc:
            # uq_approvals_open_request rejects a second open workflow for the same request.
            await self.session.rollback()
            raise AppException(
                "An approval workflow is already open for this request.",
                status_code=409,
                error_code="APPROVAL_ALREADY_OPEN",
            ) from exc
        return approval

    async def list_for_user(
        self,
        *,
        actor: User,
        box: str,
        status: str | None,
        limit: int,
        offset: int,
        status_group: str = "all",
    ) -> tuple[list[Approval], int]:
        if box not in {"inbox", "outbox"}:
            raise AppException("Invalid approval box.", status_code=422, error_code="INVALID_BOX")
        if box == "inbox":
            ensure_permission(actor, PERMISSION_REPORTS_APPROVE)
        request_types = None
        if box == "inbox":
            request_types = {"daily_report"}
            if has_permission(actor, PERMISSION_INVENTORY_MANAGE):
                request_types.add("material_request")
            if has_permission(actor, PERMISSION_DOCUMENTS_MANAGE):
                request_types.add("document")
        if status_group == "open" and status and status not in APPROVAL_PENDING_STATUSES:
            raise AppException(
                "This status is outside the open group.",
                status_code=422,
                error_code="APPROVAL_STATUS_FILTER_CONFLICT",
            )
        return await self.approvals.list_for_user(
            user_id=actor.id,
            box=box,
            status=status,
            open_only=status_group == "open",
            limit=limit,
            offset=offset,
            include_all_inbox=False,
            project_ids=(
                await accessible_project_ids(self.session, actor)
                if box == "inbox" and actor.role not in COMPANY_RESOURCE_ROLES
                else None
            ),
            request_types=request_types,
        )

    async def get_for_actor(self, approval_id: UUID, actor: User) -> Approval:
        approval = await self._get(approval_id)
        if not self._can_view(approval, actor):
            raise AppException(
                "You do not have access to this approval.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        if approval.submitter_id != actor.id:
            ensure_permission(actor, PERMISSION_REPORTS_APPROVE)
            if actor.role not in COMPANY_RESOURCE_ROLES:
                project_ids = await accessible_project_ids(self.session, actor) or []
                if approval.project_id not in project_ids:
                    raise NotFoundException("Approval")
        return approval

    async def describe_approvals(
        self, approvals: list[Approval], actor: User
    ) -> list[ApprovalResponse]:
        project_ids = (
            await accessible_project_ids(self.session, actor)
            if actor.role not in COMPANY_RESOURCE_ROLES
            else None
        )
        material_ids = [
            row.request_id for row in approvals if row.request_type == "material_request"
        ]
        invoice_ids = [row.request_id for row in approvals if row.request_type == "invoice"]
        ready_materials: set[UUID] = set()
        ready_invoices: set[UUID] = set()
        if material_ids:
            ready_materials = set(
                await self.session.scalars(
                    select(MaterialRequest.id).where(
                        MaterialRequest.id.in_(material_ids),
                        MaterialRequest.deleted_at.is_(None),
                        MaterialRequest.status == "requested",
                    )
                )
            )
        if invoice_ids:
            ready_invoices = set(
                await self.session.scalars(
                    select(Invoice.id).where(
                        Invoice.id.in_(invoice_ids),
                        Invoice.deleted_at.is_(None),
                        Invoice.status == "submitted",
                        Invoice.created_by.is_distinct_from(actor.id),
                    )
                )
            )
        responses = []
        for approval in approvals:
            response = ApprovalResponse.model_validate(approval)
            if approval.status in APPROVAL_PENDING_STATUSES and approval.request_type not in {
                "daily_report",
                "document",
            }:
                eligible = approval.request_type not in {
                    "material_request",
                    "invoice",
                } or approval.request_id in (
                    ready_materials
                    if approval.request_type == "material_request"
                    else ready_invoices
                )
                if eligible:
                    if self._can_act(approval, actor, project_ids=project_ids):
                        response.allowed_actions.extend(["approve", "reject", "delegate"])
            responses.append(response)
        return responses

    async def approve(self, approval_id: UUID, actor: User, comments: str | None) -> Approval:
        approval = await self._get_actionable(approval_id, actor)
        approval.status = "approved"
        approval.decision_comments = comments
        approval.decided_at = utc_now()
        await self._apply_entity_decision(approval, actor, "approved", comments)
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
        await self._apply_entity_decision(approval, actor, "rejected", comments.strip())
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

    async def resolve_for_entity(
        self,
        *,
        request_type: str,
        request_id: UUID,
        decision: str,
        actor: User,
        comments: str | None = None,
    ) -> Approval | None:
        """Finalise the open approval for an entity its owning service has already decided.

        The owning service authorises the actor itself (finance requires an Operation
        Manager to approve an invoice), so the inbox's `_can_act` check does not apply here.
        Without this the approval stays pending after the invoice was approved, and a later
        inbox decision could silently flip the invoice back.
        """
        approval = await self.approvals.get_open_for_request(request_type, request_id)
        if approval is None:
            return None
        approval.status = decision
        approval.decision_comments = comments
        approval.decided_at = utc_now()
        await self._notify_submitter(
            approval,
            "Approval completed" if decision == "approved" else "Approval rejected",
            f"{approval.title} was {decision}.",
        )
        await self.audit.record(
            action=f"approvals.{decision}",
            user_id=actor.id,
            entity_type=approval.request_type,
            entity_id=approval.request_id,
            new_values={
                "approval_id": str(approval.id),
                "comments": comments,
                "resolved_from": request_type,
            },
        )
        return approval

    async def cancel_material_request_approvals(self, request_id: UUID, actor: User) -> None:
        # The caller holds the material request lock before taking these approval locks.
        for approval in await self.approvals.lock_open_for_request("material_request", request_id):
            approval.status = "cancelled"
            approval.decided_at = utc_now()
            approval.decision_comments = "The requester or inventory manager cancelled the request."
            await self.audit.record(
                action="approvals.cancelled",
                user_id=actor.id,
                entity_type="material_request",
                entity_id=request_id,
                new_values={"approval_id": str(approval.id), "reason": approval.decision_comments},
            )

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
        await self._ensure_delegate_eligible(approval, actor, delegated_to)
        previous_delegate = approval.delegated_to_id
        approval.status = "delegated"
        approval.delegated_to_id = delegated_to.id
        approval.delegation_reason = reason
        await self.notifications.create(
            user_id=delegated_to.id,
            title="Approval delegated",
            body=append_link(
                f"{approval.title} was delegated to you.",
                label="Open approval",
                url=approval_inbox_url(tab="workflow", approval_id=approval.id),
            ),
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

    async def list_delegation_candidates(
        self,
        approval_id: UUID,
        actor: User,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Active users who may receive this approval, using the same rules as `delegate`.

        Group and MEP Project Managers lack `users:read`, so the picker is served from the approval
        itself rather than the company-wide user directory. Only the eligible role set is
        returned, and Group and MEP Project Managers are narrowed to members of the
        approval's project.
        """
        approval = await self._get(approval_id)
        project_ids = (
            await accessible_project_ids(self.session, actor)
            if actor.role not in COMPANY_RESOURCE_ROLES
            else None
        )
        if approval.status not in APPROVAL_PENDING_STATUSES or not self._can_act(
            approval, actor, project_ids=project_ids
        ):
            raise AppException(
                "You cannot act on this approval.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        await self._ensure_entity_actionable(approval, actor)
        eligible = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, frozenset())
        query = select(User).where(
            User.role.in_(eligible),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            User.id != actor.id,
        )
        if approval.submitter_id:
            query = query.where(User.id != approval.submitter_id)
        if approval.request_type == "invoice":
            query = query.where(
                User.id.is_distinct_from(
                    select(Invoice.created_by)
                    .where(Invoice.id == approval.request_id)
                    .scalar_subquery()
                )
            )
        if approval.project_id is None:
            query = query.where(User.role.in_(COMPANY_RESOURCE_ROLES))
            ordering: list[ColumnElement[Any]] = [User.full_name.asc(), User.id.asc()]
        else:
            membership = (
                select(ProjectMember.id)
                .where(
                    ProjectMember.project_id == approval.project_id,
                    ProjectMember.user_id == User.id,
                    ProjectMember.deleted_at.is_(None),
                )
                .exists()
            )
            query = query.where(or_(User.role.in_(COMPANY_RESOURCE_ROLES), membership))
            # Project members are preferred, then company-wide directors; both remain
            # searchable beyond the first page instead of disappearing at a fixed cap.
            ordering = [
                case(
                    (membership, 0),
                    (User.role.in_(COMPANY_RESOURCE_ROLES), 1),
                    else_=2,
                ),
                User.full_name.asc(),
                User.id.asc(),
            ]
        if search and search.strip():
            query = query.where(User.full_name.ilike(f"%{search.strip()}%"))
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(query.order_by(None).subquery())
            )
            or 0
        )
        candidates = await self.session.scalars(
            query.order_by(*ordering).limit(limit).offset(offset)
        )
        return list(candidates), total

    async def override(
        self,
        approval_id: UUID,
        actor: User,
        decision: str,
        reason: str,
    ) -> Approval:
        raise AppException(
            "Approval overrides are disabled by the active role policy.",
            status_code=403,
            error_code="APPROVAL_OVERRIDE_FORBIDDEN",
        )

    async def send_reminders_and_escalations(self) -> tuple[int, int]:
        now = utc_now()
        reminded = 0
        escalated = 0
        escalation_cutoff = now - timedelta(hours=24)
        candidates = {
            approval.id: (approval.request_type, approval.request_id, approval.id)
            for approval in [
                *await self.approvals.list_due_for_reminder(now),
                *await self.approvals.list_due_for_escalation(escalation_cutoff),
            ]
        }
        for _, _, approval_id in sorted(candidates.values()):
            try:
                approval = await self._get(approval_id, for_update=True)
            except NotFoundException:
                continue
            if approval.status not in {"pending", "delegated"}:
                continue
            if approval.request_type == "material_request" and (
                await self._material_request_status(approval.request_id) != "requested"
            ):
                continue
            recipient_id = approval.delegated_to_id or approval.approver_id
            if (
                recipient_id
                and approval.reminded_at is None
                and approval.due_at <= now
                and await self._approval_recipient_has_current_scope(approval, recipient_id)
            ):
                await self.notifications.create(
                    user_id=recipient_id,
                    title=APPROVAL_REMINDER_TITLE,
                    body=append_link(
                        f"{approval.title} is still waiting for approval.",
                        label="Open approval",
                        url=approval_inbox_url(tab="workflow", approval_id=approval.id),
                    ),
                    notification_type="approval",
                    reference_type="approvals",
                    reference_id=approval.id,
                )
                approval.reminded_at = now
                reminded += 1
            if (
                approval.escalation_user_id
                and approval.escalation_user_id != approval.approver_id
                and approval.escalated_at is None
                and approval.due_at <= escalation_cutoff
                and await self._approval_recipient_has_current_scope(
                    approval, approval.escalation_user_id
                )
            ):
                await self.notifications.create(
                    user_id=approval.escalation_user_id,
                    title=APPROVAL_ESCALATION_TITLE,
                    body=append_link(
                        f"{approval.title} has been pending for more than 48 hours.",
                        label="Open approval",
                        url=approval_inbox_url(tab="workflow", approval_id=approval.id),
                    ),
                    notification_type="approval",
                    reference_type="approvals",
                    reference_id=approval.id,
                )
                approval.status = "escalated"
                approval.escalated_at = now
                escalated += 1
        await self.session.commit()
        return reminded, escalated

    async def can_deliver_scheduled_email(self, notification: Notification) -> bool:
        if notification.notification_type != "approval":
            return True
        if notification.reference_type == "daily_report":
            return await self._can_deliver_report_notification(notification)
        if notification.reference_type != "approvals":
            return True
        if notification.reference_id is None:
            return False
        approval = await self.approvals.get_by_id(notification.reference_id)
        if approval is None:
            return False
        # Hold the owning parent before the approval row while checking the current
        # recipient and request state. A queued message must not preserve old authority.
        try:
            approval = await self._get(approval.id, for_update=True)
        except NotFoundException:
            return False
        expected_user_id: UUID | None = None
        if notification.title == "Approval pending":
            if approval.status != "pending":
                return False
            expected_user_id = approval.approver_id
        elif notification.title == "Approval delegated":
            if approval.status != "delegated":
                return False
            expected_user_id = approval.delegated_to_id
        elif notification.title == APPROVAL_REMINDER_TITLE:
            if approval.status not in {"pending", "delegated"}:
                return False
            expected_user_id = approval.delegated_to_id or approval.approver_id
        elif notification.title == APPROVAL_ESCALATION_TITLE:
            if (
                approval.status != "escalated"
                or approval.escalation_user_id == approval.approver_id
            ):
                return False
            expected_user_id = approval.escalation_user_id
        elif notification.title in {"Approval completed", "Approval rejected"}:
            expected_status = (
                "approved" if notification.title == "Approval completed" else "rejected"
            )
            if approval.status != expected_status:
                return False
            return await self._active_user_matches(notification.user_id, approval.submitter_id)
        else:
            return False
        if expected_user_id is None or notification.user_id != expected_user_id:
            return False
        return await self._approval_recipient_has_current_scope(approval, expected_user_id)

    async def _can_deliver_report_notification(self, notification: Notification) -> bool:
        if notification.reference_id is None:
            return False
        report = await self.session.scalar(
            select(DailyReport).where(
                DailyReport.id == notification.reference_id,
                DailyReport.deleted_at.is_(None),
            )
        )
        recipient = await self.users.get_by_id(notification.user_id)
        if report is None or recipient is None or not recipient.is_active:
            return False
        if notification.title == "Daily report pending approval":
            if report.status != "submitted" or recipient.id == report.engineer_id:
                return False
            if recipient.role not in REPORT_APPROVER_ROLES or not has_permission(
                recipient, PERMISSION_REPORTS_APPROVE
            ):
                return False
            if recipient.role in COMPANY_RESOURCE_ROLES:
                return True
            return bool(
                await self.session.scalar(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == report.project_id,
                        ProjectMember.user_id == recipient.id,
                        ProjectMember.deleted_at.is_(None),
                    )
                )
            )
        if notification.title == "Daily report approved":
            return (
                report.engineer_id == recipient.id
                and report.status == "approved"
                and has_permission(recipient, PERMISSION_REPORTS_SUBMIT)
            )
        if notification.title == "Daily report rejected":
            return (
                report.engineer_id == recipient.id
                and report.status == "draft"
                and has_permission(recipient, PERMISSION_REPORTS_SUBMIT)
            )
        return False

    async def _get(self, approval_id: UUID, *, for_update: bool = False) -> Approval:
        approval = await self.approvals.get_by_id(approval_id)
        if approval and for_update:
            if approval.request_type == "invoice":
                # Finance also locks the invoice before the approval.
                await self.session.scalar(
                    select(Invoice.id).where(Invoice.id == approval.request_id).with_for_update()
                )
            elif approval.request_type == "material_request":
                await self.session.scalar(
                    select(MaterialRequest.id)
                    .where(MaterialRequest.id == approval.request_id)
                    .with_for_update()
                )
            elif approval.request_type == "daily_report":
                await self.session.scalar(
                    select(DailyReport.id)
                    .where(DailyReport.id == approval.request_id)
                    .with_for_update()
                )
            elif approval.request_type == "document":
                await self.session.scalar(
                    select(Document.id)
                    .where(Document.id == approval.request_id)
                    .with_for_update()
                )
            approval = await self.approvals.get_by_id(approval_id, for_update=True)
        if not approval:
            raise NotFoundException("Approval")
        return approval

    async def _get_actionable(self, approval_id: UUID, actor: User) -> Approval:
        approval = await self._get(approval_id, for_update=True)
        if approval.status not in APPROVAL_PENDING_STATUSES:
            raise AppException(
                "Approval is already final.",
                status_code=409,
                error_code="APPROVAL_FINAL",
            )
        project_ids = (
            await accessible_project_ids(self.session, actor)
            if actor.role not in COMPANY_RESOURCE_ROLES
            else None
        )
        if not self._can_act(approval, actor, project_ids=project_ids):
            raise AppException(
                "You cannot act on this approval.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        await self._ensure_entity_actionable(approval, actor)
        return approval

    async def _material_request_status(self, request_id: UUID) -> str | None:
        return await self.session.scalar(
            select(MaterialRequest.status).where(
                MaterialRequest.id == request_id, MaterialRequest.deleted_at.is_(None)
            )
        )

    async def _ensure_entity_actionable(self, approval: Approval, actor: User) -> None:
        if approval.request_type in {"daily_report", "document"}:
            raise AppException(
                "Decide this record in its owning workflow.",
                status_code=409,
                error_code="APPROVAL_REQUIRES_OWNING_WORKFLOW",
            )
        if approval.request_type == "invoice":
            raise AppException(
                "Invoice decisions are disabled by the read-only finance policy.",
                status_code=403,
                error_code="FINANCE_WRITE_FORBIDDEN",
            )
        if approval.request_type != "material_request":
            return
        status = await self._material_request_status(approval.request_id)
        if status is None:
            raise NotFoundException("Material request")
        if status != "requested":
            raise AppException(
                "Only requested material requests can be decided.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )

    async def _resolve_approver(self, payload: ApprovalCreateRequest, actor: User) -> User:
        eligible_roles = set(DELEGATION_ELIGIBLE_ROLES.get(payload.request_type, frozenset()))
        if not eligible_roles:
            raise AppException(
                "No decision permission is defined for this approval type.",
                status_code=403,
                error_code="APPROVAL_TYPE_FORBIDDEN",
            )
        approver = await self._first_active_scoped_approver(
            payload.project_id, eligible_roles, excluded_user_ids={actor.id}
        )
        if approver:
            return approver
        raise AppException(
            "No active approver is configured.",
            status_code=409,
            error_code="APPROVER_NOT_CONFIGURED",
        )

    async def _first_active_scoped_approver(
        self,
        project_id: UUID | None,
        roles: set[str],
        *,
        excluded_user_ids: set[UUID] | None = None,
    ) -> User | None:
        excluded_user_ids = excluded_user_ids or set()
        if project_id and roles:
            project_query = (
                select(User)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.deleted_at.is_(None),
                    User.role.in_(roles),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
            if excluded_user_ids:
                project_query = project_query.where(User.id.not_in(excluded_user_ids))
            project_user = await self.session.scalar(
                project_query.order_by(ProjectMember.assigned_at.desc(), User.full_name.asc())
            )
            if project_user is not None:
                return project_user
        # Only explicit company-resource roles may be a projectless fallback. A
        # scoped HR/project role without membership is never selected globally.
        return await self._first_active_role_user(
            roles & COMPANY_RESOURCE_ROLES, excluded_user_ids=excluded_user_ids
        )

    async def _first_active_role_user(
        self, roles: set[str], *, excluded_user_ids: set[UUID] | None = None
    ) -> User | None:
        if not roles:
            return None
        query = select(User).where(
            User.role.in_(roles), User.is_active.is_(True), User.deleted_at.is_(None)
        )
        if excluded_user_ids:
            query = query.where(User.id.not_in(excluded_user_ids))
        ordered_query = query.order_by(User.created_at.desc(), User.full_name.asc())
        return await self.session.scalar(ordered_query)

    async def _active_user_matches(
        self, actual_user_id: UUID, expected_user_id: UUID | None
    ) -> bool:
        if expected_user_id is None or actual_user_id != expected_user_id:
            return False
        return bool(
            await self.session.scalar(
                select(User.id).where(
                    User.id == actual_user_id,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
            )
        )

    async def _approval_recipient_has_current_scope(
        self, approval: Approval, recipient_id: UUID
    ) -> bool:
        permission = {
            "daily_report": PERMISSION_REPORTS_APPROVE,
            "document": PERMISSION_DOCUMENTS_MANAGE,
            "material_request": PERMISSION_INVENTORY_MANAGE,
        }.get(approval.request_type)
        if permission is None:
            return False
        recipient = await self.session.scalar(
            select(User).where(
                User.id == recipient_id,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
            )
        )
        if (
            recipient is None
            or recipient.id == approval.submitter_id
            or recipient.role not in DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, ())
            or not has_permission(recipient, permission)
        ):
            return False
        if approval.request_type == "material_request":
            if await self._material_request_status(approval.request_id) != "requested":
                return False
        elif approval.request_type == "daily_report":
            report = await self.session.scalar(
                select(DailyReport).where(
                    DailyReport.id == approval.request_id,
                    DailyReport.deleted_at.is_(None),
                    DailyReport.status == "submitted",
                )
            )
            if report is None or report.engineer_id == recipient.id:
                return False
        elif approval.request_type == "document":
            document = await self.session.scalar(
                select(Document).where(
                    Document.id == approval.request_id,
                    Document.deleted_at.is_(None),
                    Document.status == "pending_approval",
                )
            )
            if document is None:
                return False
        if recipient.role in COMPANY_RESOURCE_ROLES:
            return True
        if approval.project_id is None:
            return False
        return bool(
            await self.session.scalar(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == approval.project_id,
                    ProjectMember.user_id == recipient.id,
                    ProjectMember.deleted_at.is_(None),
                )
            )
        )

    async def _ensure_delegate_eligible(
        self,
        approval: Approval,
        actor: User,
        delegate: User,
    ) -> None:
        """Guard delegation at the point the decision power is handed over.

        `_can_act` deliberately stays permissive (approver or delegate); the checks that
        stop self-approval, submitter-approval and unqualified delegates belong here.
        """
        if delegate.id == actor.id:
            raise AppException(
                "You cannot delegate an approval to yourself.",
                status_code=403,
                error_code="DELEGATION_TO_SELF_FORBIDDEN",
            )
        invoice_creator = (
            await self.session.scalar(
                select(Invoice.created_by).where(Invoice.id == approval.request_id)
            )
            if approval.request_type == "invoice"
            else None
        )
        if delegate.id in {approval.submitter_id, invoice_creator}:
            raise AppException(
                "The creator or submitter cannot approve their own request.",
                status_code=403,
                error_code="DELEGATION_TO_SUBMITTER_FORBIDDEN",
            )
        eligible = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, frozenset())
        if delegate.role not in eligible:
            raise AppException(
                "This user cannot approve this request type.",
                status_code=403,
                error_code="DELEGATION_ROLE_FORBIDDEN",
            )
        if delegate.role in COMPANY_RESOURCE_ROLES:
            # Company-wide approvers are unrestricted, mirroring the owning workflows.
            return
        if approval.project_id is None:
            # Scoped roles cannot decide an unassigned project request.
            raise AppException(
                "A Group or MEP Project Manager cannot approve requests outside a project.",
                status_code=403,
                error_code="DELEGATION_PROJECT_FORBIDDEN",
            )
        membership = await self.session.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == approval.project_id,
                ProjectMember.user_id == delegate.id,
                ProjectMember.deleted_at.is_(None),
            )
        )
        if membership is None:
            raise AppException(
                "The delegate is not a member of this project.",
                status_code=403,
                error_code="DELEGATION_PROJECT_FORBIDDEN",
            )

    def _can_view(self, approval: Approval, actor: User) -> bool:
        if actor.id == approval.submitter_id:
            return True
        if not self._has_request_type_permission(approval.request_type, actor):
            return False
        return actor.id in {
            approval.submitter_id,
            approval.approver_id,
            approval.delegated_to_id,
        } or (approval.status == "escalated" and actor.id == approval.escalation_user_id)

    @staticmethod
    def _self_invoice(approval: Approval, actor: User) -> bool:
        return approval.request_type == "invoice" and actor.id == approval.submitter_id

    def _can_act(self, approval: Approval, actor: User, *, project_ids: list[UUID] | None) -> bool:
        roles = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, frozenset())
        return (
            actor.id in {approval.approver_id, approval.delegated_to_id}
            and actor.role in roles
            and self._has_request_type_permission(approval.request_type, actor)
            and not self._self_invoice(approval, actor)
            and (actor.role in COMPANY_RESOURCE_ROLES or approval.project_id in (project_ids or []))
        )

    @staticmethod
    def _has_request_type_permission(request_type: str, actor: User) -> bool:
        permission = {
            "daily_report": PERMISSION_REPORTS_APPROVE,
            "document": PERMISSION_DOCUMENTS_MANAGE,
            "material_request": PERMISSION_INVENTORY_MANAGE,
        }.get(request_type)
        return permission is not None and has_permission(actor, permission)

    async def _apply_entity_decision(
        self,
        approval: Approval,
        actor: User,
        decision: str,
        comments: str | None,
    ) -> None:
        if approval.request_type == "material_request":
            request = await self.session.scalar(
                select(MaterialRequest)
                .where(
                    MaterialRequest.id == approval.request_id,
                    MaterialRequest.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if request is None:
                raise NotFoundException("Material request")
            if request.status != "requested":
                raise AppException(
                    "Only requested material requests can be decided.",
                    status_code=409,
                    error_code="REQUEST_STATUS_INVALID",
                )
            request.status = "approved" if decision == "approved" else "cancelled"
            request.revision += 1
        elif approval.request_type == "invoice":
            invoice = await self.session.scalar(
                select(Invoice)
                .where(
                    Invoice.id == approval.request_id,
                    Invoice.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if not invoice:
                raise NotFoundException("Invoice")
            if invoice.status != "submitted":
                raise AppException(
                    "Only submitted invoices can be decided from the approval inbox.",
                    status_code=409,
                    error_code="INVOICE_STATUS_TRANSITION_INVALID",
                )
            if decision == "rejected" and any(
                payment.deleted_at is None for payment in invoice.payments
            ):
                raise AppException(
                    "This invoice has recorded payments and requires an accounting reversal.",
                    status_code=409,
                    error_code="INVOICE_HAS_PAYMENTS",
                )
            invoice.status = "approved" if decision == "approved" else "rejected"
            invoice.revision += 1
            if decision == "approved":
                invoice.approved_by = actor.id
                invoice.approved_at = utc_now()
        elif approval.request_type in {"payment", "project_change"}:
            await self.audit.record(
                action=f"{approval.request_type}.approval_decision",
                user_id=actor.id,
                entity_type=approval.request_type,
                entity_id=approval.request_id,
                new_values={"decision": decision, "approval_id": str(approval.id)},
                comments=comments,
            )

    async def _notify_submitter(self, approval: Approval, title: str, body: str) -> None:
        if approval.submitter_id:
            await self.notifications.create(
                user_id=approval.submitter_id,
                title=title,
                body=append_link(
                    body,
                    label=self._submitter_link_label(approval),
                    url=self._submitter_target_url(approval),
                ),
                notification_type="approval",
                reference_type="approvals",
                reference_id=approval.id,
            )

    def _submitter_target_url(self, approval: Approval) -> str | None:
        if approval.request_type == "invoice":
            return finance_invoice_url(approval.request_id)
        if approval.request_type == "material_request":
            return material_request_url(approval.request_id)
        if approval.request_type == "daily_report":
            return daily_report_url(approval.request_id)
        if approval.request_type == "document":
            return document_url(approval.request_id)
        return None

    def _submitter_link_label(self, approval: Approval) -> str:
        if approval.request_type == "invoice":
            return "Open invoice"
        if approval.request_type == "material_request":
            return "Open material request"
        if approval.request_type == "daily_report":
            return "Open report"
        if approval.request_type == "document":
            return "Open document"
        return "Open request"
