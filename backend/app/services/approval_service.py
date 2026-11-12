from datetime import timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import case, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.finance import Invoice
from app.models.inventory import MaterialRequest
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
    PERMISSION_REPORTS_APPROVE,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
    ensure_permission,
)
from app.utils.security import utc_now

APPROVAL_PENDING_STATUSES = {"pending", "delegated", "escalated"}
ENTITY_BACKED_REQUEST_TYPES = {"material_request", "invoice", "daily_report", "document"}

# Roles that may actually decide each request type. Delegation must not hand decision
# power to someone the owning workflow would reject: `_apply_entity_decision` writes the
# decision directly and never re-runs the downstream service guards.
_GENERIC_DECISION_ROLES = frozenset({ROLE_ADMIN, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER})
DELEGATION_ELIGIBLE_ROLES: dict[str, frozenset[str]] = {
    # finance_service.update_invoice requires Operation Manager approval.
    "invoice": frozenset({ROLE_ADMIN, ROLE_OPERATION_MANAGER}),
    # report_service._ensure_approver also accepts General Manager.
    "daily_report": frozenset(
        {ROLE_ADMIN, ROLE_GENERAL_MANAGER, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER}
    ),
    "document": _GENERIC_DECISION_ROLES,
    "material_request": _GENERIC_DECISION_ROLES,
    "payment": _GENERIC_DECISION_ROLES,
    "project_change": _GENERIC_DECISION_ROLES,
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
        escalation_user = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
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
            include_all_inbox=actor.role == ROLE_ADMIN and box == "inbox",
            project_ids=(
                await accessible_project_ids(self.session, actor)
                if box == "inbox" and actor.role == ROLE_PROJECT_MANAGER
                else None
            ),
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
            if actor.role == ROLE_PROJECT_MANAGER:
                project_ids = await accessible_project_ids(self.session, actor) or []
                if approval.project_id not in project_ids:
                    raise NotFoundException("Approval")
        return approval

    async def describe_approvals(
        self, approvals: list[Approval], actor: User
    ) -> list[ApprovalResponse]:
        project_ids = (
            await accessible_project_ids(self.session, actor)
            if actor.role == ROLE_PROJECT_MANAGER
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
                    if actor.role == ROLE_ADMIN and not self._self_invoice(approval, actor):
                        response.allowed_actions.append("override")
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

    async def list_delegation_candidates(self, approval_id: UUID, actor: User) -> list[User]:
        """Active users who may receive this approval, using the same rules as `delegate`.

        Project Managers lack `users:read`, so the picker is served from the approval
        itself rather than the company-wide user directory. Only the eligible role set is
        returned, and Project Managers are narrowed to members of the approval's project.
        """
        approval = await self._get(approval_id)
        project_ids = (
            await accessible_project_ids(self.session, actor)
            if actor.role == ROLE_PROJECT_MANAGER
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
        eligible = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, _GENERIC_DECISION_ROLES)
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
            query = query.where(User.role != ROLE_PROJECT_MANAGER)
            return list(await self.session.scalars(query.order_by(User.full_name.asc()).limit(200)))
        membership = (
            select(ProjectMember.id)
            .where(
                ProjectMember.project_id == approval.project_id,
                ProjectMember.user_id == User.id,
                ProjectMember.deleted_at.is_(None),
            )
            .exists()
        )
        query = query.where(or_(User.role != ROLE_PROJECT_MANAGER, membership))
        # The project's own people are the natural delegates, and the alphabetical cap
        # must not crowd them out of a large company directory.
        query = query.order_by(case((membership, 0), else_=1), User.full_name.asc())
        candidates = await self.session.scalars(query.limit(200))
        return list(candidates)

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
        approval = await self._get(approval_id, for_update=True)
        if approval.status not in APPROVAL_PENDING_STATUSES:
            raise AppException(
                "Only pending approvals can be overridden.",
                status_code=409,
                error_code="APPROVAL_FINAL",
            )
        if self._self_invoice(approval, actor):
            raise AppException(
                "The invoice submitter cannot decide it.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        await self._ensure_entity_actionable(approval, actor)
        approval.status = f"override_{decision}"
        approval.override_reason = reason
        approval.decided_at = utc_now()
        await self._apply_entity_decision(approval, actor, decision, reason)
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
            if recipient_id and approval.reminded_at is None and approval.due_at <= now:
                await self.notifications.create(
                    user_id=recipient_id,
                    title="Approval reminder",
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
                and approval.escalated_at is None
                and approval.due_at <= escalation_cutoff
            ):
                await self.notifications.create(
                    user_id=approval.escalation_user_id,
                    title="Approval escalated",
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
            if actor.role == ROLE_PROJECT_MANAGER
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
            invoice = (
                await self.session.execute(
                    select(Invoice.status, Invoice.created_by).where(
                        Invoice.id == approval.request_id, Invoice.deleted_at.is_(None)
                    )
                )
            ).one_or_none()
            if invoice is None:
                raise NotFoundException("Invoice")
            if invoice.created_by == actor.id:
                raise AppException(
                    "The invoice creator cannot decide it.",
                    status_code=403,
                    error_code="APPROVAL_FORBIDDEN",
                )
            if invoice.status != "submitted":
                raise AppException(
                    "Only submitted invoices can be decided.",
                    status_code=409,
                    error_code="INVOICE_STATUS_TRANSITION_INVALID",
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
        if payload.request_type == "invoice":
            approver = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
            if approver:
                return approver
        if (
            payload.request_type == "material_request"
            and payload.amount is not None
            and payload.amount > Decimal("1000.00")
        ):
            approver = await self._first_active_role_user(ROLE_OPERATION_MANAGER)
            if approver:
                return approver
        if (
            payload.request_type in {"material_request", "project_change"}
            and actor.role == ROLE_PROJECT_MANAGER
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
                    User.id != actor.id,
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                )
                .order_by(ProjectMember.assigned_at.desc(), User.full_name.asc())
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
            .order_by(User.created_at.desc(), User.full_name.asc())
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
        eligible = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, _GENERIC_DECISION_ROLES)
        if delegate.role not in eligible:
            raise AppException(
                "This user cannot approve this request type.",
                status_code=403,
                error_code="DELEGATION_ROLE_FORBIDDEN",
            )
        if delegate.role != ROLE_PROJECT_MANAGER:
            # Company-wide approvers are unrestricted, mirroring the owning workflows.
            return
        if approval.project_id is None:
            # document_service._ensure_approver reserves unscoped documents for admin/OM.
            raise AppException(
                "A Project Manager cannot approve requests outside a project.",
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
        return (
            actor.role == ROLE_ADMIN
            or actor.id
            in {
                approval.submitter_id,
                approval.approver_id,
                approval.delegated_to_id,
            }
            or (approval.status == "escalated" and actor.id == approval.escalation_user_id)
        )

    @staticmethod
    def _self_invoice(approval: Approval, actor: User) -> bool:
        return approval.request_type == "invoice" and actor.id == approval.submitter_id

    def _can_act(self, approval: Approval, actor: User, *, project_ids: list[UUID] | None) -> bool:
        roles = DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, _GENERIC_DECISION_ROLES)
        return (
            actor.id in {approval.approver_id, approval.delegated_to_id}
            and actor.role in roles
            and not self._self_invoice(approval, actor)
            and (actor.role != ROLE_PROJECT_MANAGER or approval.project_id in (project_ids or []))
        )

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
