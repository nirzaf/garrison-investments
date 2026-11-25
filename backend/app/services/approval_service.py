from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.approval import Approval
from app.models.daily_report import DailyReport
from app.models.document import Document
from app.models.finance import Invoice
from app.models.inventory import MaterialRequest, MaterialRequestLine, MaterialRequestSubmission
from app.models.notification import Notification
from app.models.project import Project
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
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_REPORTS_APPROVE,
    PERMISSION_REPORTS_SUBMIT,
    REPORT_APPROVER_ROLES,
    ROLE_ADMINISTRATIVE_EXECUTIVE,
    ROLE_GROUP_PROJECT_MANAGER,
    ROLE_MANAGING_DIRECTOR,
    ROLE_MEP_PROJECT_MANAGER,
    ROLE_OPERATIONS_DIRECTOR,
    ensure_permission,
    has_permission,
    roles_with_permission,
)
from app.utils.security import utc_now

APPROVAL_PENDING_STATUSES = {"pending", "delegated", "escalated"}
ENTITY_BACKED_REQUEST_TYPES = {"material_request", "invoice", "daily_report", "document"}
OPERATING_CURRENCY_APPROVAL_TYPES = {"material_request", "invoice"}
MATERIAL_STAGE_ROLES = {
    1: ROLE_MEP_PROJECT_MANAGER,
    2: ROLE_GROUP_PROJECT_MANAGER,
    3: ROLE_OPERATIONS_DIRECTOR,
    4: ROLE_MANAGING_DIRECTOR,
}
MATERIAL_STAGE_STATES = {
    1: "pending_engineer",
    2: "pending_gpm",
    3: "pending_operations",
    4: "pending_md",
}
MATERIAL_STAGE_TITLES = {2: "GPM approval", 3: "Operations approval", 4: "MD approval"}
APPROVAL_REMINDER_TITLE = "Approval reminder"
APPROVAL_ESCALATION_TITLE = "Approval escalated"
MATERIAL_OVERDUE_TITLE = "Material approval overdue"
MATERIAL_FULFILLMENT_TITLE = "Material request ready for fulfillment"

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


def required_material_stages(total: Decimal | None) -> tuple[int, ...]:
    settings = get_settings()
    return (1, 2) + tuple(
        stage
        for stage, threshold in (
            (3, settings.material_operations_approval_threshold),
            (4, settings.material_md_approval_threshold),
        )
        if threshold is not None and (total is None or total >= threshold)
    )


def frozen_material_stages(submission: MaterialRequestSubmission) -> tuple[int, ...]:
    requirements = submission.requirements
    if not isinstance(requirements, dict):
        return ()
    stages = requirements.get("approval_stages", [1, 2])
    if not isinstance(stages, list) or any(type(stage) is not int for stage in stages):
        return ()
    ordered = tuple(stages)
    return ordered if ordered in {(1, 2), (1, 2, 3), (1, 2, 4), (1, 2, 3, 4)} else ()


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
        material_submission: MaterialRequestSubmission | None = None,
        step_order: int = 1,
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
        if material_submission is not None:
            if step_order == 1:
                material_submission.requirements = {
                    **material_submission.requirements,
                    "approval_stages": list(required_material_stages(payload.amount)),
                }
            excluded = {material_submission.submitted_by, actor.id}
            role = MATERIAL_STAGE_ROLES[step_order]
            if step_order in (1, 2):
                approver = await self.require_project_reviewer(
                    payload.project_id,
                    role,
                    approver_id={
                        1: material_submission.engineer_id,
                        2: material_submission.manager_id,
                    }[step_order],
                    excluded_user_ids=excluded,
                )
            else:
                earlier = await self._material_deciders(
                    payload.request_id, material_submission.submission_revision, step_order
                )
                director = await self._first_active_scoped_approver(
                    payload.project_id, {role}, excluded_user_ids=excluded | set(earlier.values())
                )
                if director is None:
                    raise AppException(
                        "An active independent director must be available for this stage.",
                        status_code=409,
                        error_code="APPROVER_NOT_CONFIGURED",
                    )
                approver = director
            escalation_user = None
        else:
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
                    submitter_id=(
                        material_submission.submitted_by if material_submission else actor.id
                    ),
                    approver_id=approver.id,
                    submission_revision=(
                        material_submission.submission_revision if material_submission else None
                    ),
                    step_order=step_order,
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
            if has_permission(actor, PERMISSION_INVENTORY_MANAGE) or (
                actor.role in MATERIAL_STAGE_ROLES.values()
            ):
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
            include_overdue_material=actor.role in COMPANY_RESOURCE_ROLES,
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
        material_submission_keys = {
            (row.request_id, row.submission_revision)
            for row in approvals
            if row.request_type == "material_request" and row.submission_revision is not None
        }
        invoice_ids = [row.request_id for row in approvals if row.request_type == "invoice"]
        ready_materials: set[UUID] = set()
        ready_invoices: set[UUID] = set()
        complete_valuations: set[tuple[UUID, int]] = set()
        if material_ids:
            ready_materials = set(
                await self.session.scalars(
                    select(MaterialRequest.id).where(
                        MaterialRequest.id.in_(material_ids),
                        MaterialRequest.deleted_at.is_(None),
                        MaterialRequest.status.in_(["requested", *MATERIAL_STAGE_STATES.values()]),
                    )
                )
            )
        if material_submission_keys:
            valuation_rows = (
                await self.session.execute(
                select(
                    MaterialRequestSubmission.request_id,
                    MaterialRequestSubmission.submission_revision,
                    MaterialRequestSubmission.requirements,
                ).where(
                    tuple_(
                        MaterialRequestSubmission.request_id,
                        MaterialRequestSubmission.submission_revision,
                    ).in_(material_submission_keys)
                )
                )
            ).all()
            complete_valuations = {
                (request_id, revision)
                for request_id, revision, requirements in valuation_rows
                if isinstance(requirements, dict)
                and (
                    requirements.get("valuation_status") == "complete"
                    or requirements.get("valuation_complete") is True
                )
            }
            legacy_keys = {
                (request_id, revision)
                for request_id, revision, requirements in valuation_rows
                if isinstance(requirements, dict)
                and "valuation_status" not in requirements
                and "valuation_complete" not in requirements
            }
            if legacy_keys:
                has_lines = select(MaterialRequestLine.id).where(
                    MaterialRequestLine.request_id == MaterialRequest.id,
                    MaterialRequestLine.deleted_at.is_(None),
                ).exists()
                has_unknown_line = select(MaterialRequestLine.id).where(
                    MaterialRequestLine.request_id == MaterialRequest.id,
                    MaterialRequestLine.deleted_at.is_(None),
                    MaterialRequestLine.unit_cost.is_(None),
                ).exists()
                verified_legacy = await self.session.execute(
                    select(MaterialRequest.id, MaterialRequest.submission_revision).where(
                        tuple_(MaterialRequest.id, MaterialRequest.submission_revision).in_(
                            legacy_keys
                        ),
                        MaterialRequest.deleted_at.is_(None),
                        has_lines,
                        ~has_unknown_line,
                    )
                )
                complete_valuations.update(
                    (request_id, revision)
                    for request_id, revision in verified_legacy.all()
                    if revision is not None
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
        can_view_financial = has_permission(actor, PERMISSION_FINANCIAL_VIEW)
        for approval in approvals:
            response = ApprovalResponse.model_validate(approval)
            if not can_view_financial or (
                project_ids is not None and approval.project_id not in project_ids
            ):
                response.amount = None
                response.currency = None
            elif (
                approval.request_type == "material_request"
                and approval.submission_revision is not None
                and (approval.request_id, approval.submission_revision) not in complete_valuations
            ):
                response.amount = None
                response.currency = None
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
                        if approval.submission_revision is not None:
                            response.allowed_actions.append("return")
            responses.append(response)
        return responses

    async def approve(
        self,
        approval_id: UUID,
        actor: User,
        comments: str | None,
        expected_submission_revision: int | None = None,
    ) -> Approval:
        approval = await self._get_actionable(approval_id, actor)
        self._check_submission_revision(approval, expected_submission_revision)
        approval.status = "approved"
        if approval.submission_revision is not None:
            approval.decided_by = actor.id
        approval.decision_comments = comments
        approval.decided_at = utc_now()
        next_stage = await self._apply_entity_decision(approval, actor, "approved", comments)
        await self._notify_submitter(
            approval,
            "Material approval advanced" if next_stage else "Approval completed",
            (
                f"{approval.title} was accepted. Next stage: {MATERIAL_STAGE_TITLES[next_stage]}."
                if next_stage
                else f"{approval.title} was approved."
            ),
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

    async def reject(
        self,
        approval_id: UUID,
        actor: User,
        comments: str | None,
        expected_submission_revision: int | None = None,
        *,
        return_for_correction: bool = False,
    ) -> Approval:
        if not comments or not comments.strip():
            raise AppException(
                "Rejection reason is required.",
                status_code=422,
                error_code="REJECTION_REASON_REQUIRED",
            )
        approval = await self._get_actionable(approval_id, actor)
        self._check_submission_revision(approval, expected_submission_revision)
        if return_for_correction and approval.submission_revision is None:
            raise AppException(
                "Return is only available for a material submission.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        decision = "returned" if return_for_correction else "rejected"
        approval.status = decision
        if approval.submission_revision is not None:
            approval.decided_by = actor.id
        approval.decision_comments = comments.strip()
        approval.decided_at = utc_now()
        await self._apply_entity_decision(approval, actor, decision, comments.strip())
        await self._notify_submitter(
            approval, f"Approval {decision}", f"{approval.title} was {decision}: {comments.strip()}"
        )
        await self.audit.record(
            action=f"approvals.{decision}",
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
        expected_submission_revision: int | None = None,
    ) -> Approval:
        approval = await self._get_actionable(approval_id, actor)
        self._check_submission_revision(approval, expected_submission_revision)
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
        eligible = self._decision_roles(approval)
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
                not await self._material_stage_is_open(approval)
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
                approval.request_type == "material_request"
                and approval.submission_revision is not None
            ):
                if approval.escalated_at is None and approval.due_at <= escalation_cutoff:
                    overdue_recipients = await self.session.scalars(
                        select(User.id).where(
                            User.role == ROLE_OPERATIONS_DIRECTOR,
                            User.is_active.is_(True),
                            User.deleted_at.is_(None),
                        )
                    )
                    recipients = list(overdue_recipients)
                    if not recipients:
                        continue
                    for recipient in recipients:
                        await self.notifications.create(
                            user_id=recipient,
                            title=MATERIAL_OVERDUE_TITLE,
                            body=append_link(
                                f"{approval.title} is overdue.",
                                label="View overdue approval",
                                url=approval_inbox_url(tab="workflow", approval_id=approval.id),
                            ),
                            notification_type="approval",
                            reference_type="approvals",
                            reference_id=approval.id,
                        )
                    approval.escalated_at = now
                    escalated += 1
                continue
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
        ready_for_fulfillment = (
            notification.notification_type == "inventory"
            and notification.title == MATERIAL_FULFILLMENT_TITLE
        )
        if ready_for_fulfillment and notification.reference_type != "approvals":
            return False
        if notification.notification_type != "approval" and not ready_for_fulfillment:
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
        elif notification.title == MATERIAL_OVERDUE_TITLE:
            if (
                approval.request_type != "material_request"
                or approval.submission_revision is None
                or approval.escalated_at is None
                or approval.status not in {"pending", "delegated"}
                or not await self._material_stage_is_open(approval)
            ):
                return False
            return bool(
                await self.session.scalar(
                    select(User.id).where(
                        User.id == notification.user_id,
                        User.role == ROLE_OPERATIONS_DIRECTOR,
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                    )
                )
            )
        elif notification.title == APPROVAL_ESCALATION_TITLE:
            if (
                approval.status != "escalated"
                or approval.escalation_user_id == approval.approver_id
            ):
                return False
            expected_user_id = approval.escalation_user_id
        elif notification.title in {
            "Material approval advanced",
            MATERIAL_FULFILLMENT_TITLE,
            "Approval completed",
            "Approval rejected",
            "Approval returned",
        }:
            if (
                approval.request_type == "material_request"
                and approval.submission_revision is not None
            ):
                return await self._can_deliver_material_decision(notification, approval)
            expected_status = {
                "Approval completed": "approved",
                "Approval rejected": "rejected",
                "Approval returned": "returned",
            }.get(notification.title)
            if (
                notification.title in {"Material approval advanced", MATERIAL_FULFILLMENT_TITLE}
                or approval.status != expected_status
            ):
                return False
            return await self._active_user_matches(notification.user_id, approval.submitter_id)
        else:
            return False
        if expected_user_id is None or notification.user_id != expected_user_id:
            return False
        return await self._approval_recipient_has_current_scope(approval, expected_user_id)

    async def _can_deliver_material_decision(
        self, notification: Notification, approval: Approval
    ) -> bool:
        request = await self.session.get(MaterialRequest, approval.request_id)
        if (
            request is None
            or request.deleted_at is not None
            or request.submission_revision != approval.submission_revision
        ):
            return False
        submission = await self.session.get(
            MaterialRequestSubmission, (approval.request_id, approval.submission_revision)
        )
        if submission is None:
            return False
        if notification.title == MATERIAL_FULFILLMENT_TITLE:
            stages = frozen_material_stages(submission)
            if (
                not stages
                or approval.step_order != stages[-1]
                or approval.status != "approved"
                or request.status
                not in {"approved", "partially_reserved", "reserved", "partially_issued"}
                or not await self._active_user_matches(
                    notification.user_id, submission.processor_id
                )
            ):
                return False
            processor = await self.users.get_by_id(notification.user_id)
            return (
                processor is not None
                and processor.role == ROLE_ADMINISTRATIVE_EXECUTIVE
                and (
                    request.project_id
                    in (await accessible_project_ids(self.session, processor) or [])
                )
            )
        if not await self._active_user_matches(notification.user_id, submission.submitted_by):
            return False
        recipient = await self.users.get_by_id(notification.user_id)
        if recipient is None or (
            recipient.role not in COMPANY_RESOURCE_ROLES
            and request.project_id
            not in (await accessible_project_ids(self.session, recipient) or [])
        ):
            return False
        if notification.title in {"Approval rejected", "Approval returned"}:
            decision = "returned" if notification.title == "Approval returned" else "rejected"
            if decision == "returned":
                stages = frozen_material_stages(submission)
                if (
                    not stages
                    or approval.step_order not in stages
                    or approval.decided_by is None
                    or approval.decided_at is None
                    or approval.decided_by == submission.submitted_by
                ):
                    return False
            return approval.status == decision and request.status == decision
        stages = frozen_material_stages(submission)
        if approval.status != "approved" or approval.step_order not in stages:
            return False
        if notification.title == "Approval completed":
            return approval.step_order == stages[-1] and request.status in {
                "approved",
                "partially_reserved",
                "reserved",
                "partially_issued",
                "issued",
            }
        if approval.step_order == stages[-1]:
            return False
        next_stage = stages[stages.index(approval.step_order) + 1]
        return request.status == MATERIAL_STAGE_STATES[next_stage]

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
                    select(Document.id).where(Document.id == approval.request_id).with_for_update()
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
        if not await self._material_stage_is_open(approval):
            raise AppException(
                "Only requested material requests can be decided.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )

    @staticmethod
    def _check_submission_revision(approval: Approval, expected: int | None) -> None:
        if approval.submission_revision is not None and approval.submission_revision != expected:
            raise AppException(
                "Refresh the submission before making a decision.",
                status_code=409,
                error_code="SUBMISSION_REVISION_CONFLICT",
            )

    @staticmethod
    def _decision_roles(approval: Approval) -> frozenset[str]:
        if approval.submission_revision is not None:
            role = MATERIAL_STAGE_ROLES.get(approval.step_order)
            return frozenset({role}) if role else frozenset()
        return DELEGATION_ELIGIBLE_ROLES.get(approval.request_type, frozenset())

    async def _material_stage_is_open(self, approval: Approval) -> bool:
        if approval.submission_revision is None:
            return await self._material_request_status(approval.request_id) == "requested"
        return bool(
            await self.session.scalar(
                select(MaterialRequest.id)
                .join(Project, Project.id == MaterialRequest.project_id)
                .where(
                    MaterialRequest.id == approval.request_id,
                    MaterialRequest.deleted_at.is_(None),
                    MaterialRequest.submission_revision == approval.submission_revision,
                    MaterialRequest.status == MATERIAL_STAGE_STATES.get(approval.step_order),
                    Project.status == "active",
                    Project.deleted_at.is_(None),
                )
            )
        )

    async def require_project_reviewer(
        self,
        project_id: UUID | None,
        role: str,
        *,
        excluded_user_ids: set[UUID],
        approver_id: UUID | None = None,
    ) -> User:
        query = (
            select(User)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.deleted_at.is_(None),
                User.role == role,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.id.not_in(excluded_user_ids),
            )
        )
        if approver_id is not None:
            query = query.where(User.id == approver_id)
        reviewer = await self.session.scalar(
            query.order_by(ProjectMember.assigned_at, User.id)
            .limit(1)
            .with_for_update(read=True, of=[User, ProjectMember])
        )
        if reviewer is not None:
            return reviewer
        raise AppException(
            "An active project member must be assigned for this review stage.",
            status_code=409,
            error_code="APPROVER_NOT_CONFIGURED",
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
            or recipient.role not in self._decision_roles(approval)
            or (approval.submission_revision is None and not has_permission(recipient, permission))
        ):
            return False
        if approval.request_type == "material_request":
            if not await self._material_stage_is_open(approval):
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
        eligible = self._decision_roles(approval)
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
        if (
            approval.request_type == "material_request"
            and approval.submission_revision is not None
            and approval.escalated_at is not None
            and approval.status in {"pending", "delegated"}
            and actor.role in COMPANY_RESOURCE_ROLES
        ):
            return True
        if approval.submission_revision is not None:
            if actor.role not in self._decision_roles(approval):
                return False
        elif not self._has_request_type_permission(approval.request_type, actor):
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
        roles = self._decision_roles(approval)
        return (
            actor.id in {approval.approver_id, approval.delegated_to_id}
            and actor.role in roles
            and (
                (approval.submission_revision is not None and actor.id != approval.submitter_id)
                or (
                    approval.submission_revision is None
                    and self._has_request_type_permission(approval.request_type, actor)
                )
            )
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
    ) -> int | None:
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
            if approval.submission_revision is not None:
                return await self._apply_material_submission_decision(
                    request, approval, actor, decision
                )
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
        return None

    async def _material_deciders(
        self, request_id: UUID, revision: int, before_stage: int
    ) -> dict[int, UUID]:
        rows = await self.session.execute(
            select(Approval.step_order, Approval.decided_by).where(
                Approval.request_type == "material_request",
                Approval.request_id == request_id,
                Approval.submission_revision == revision,
                Approval.step_order < before_stage,
                Approval.status == "approved",
                Approval.decided_by.is_not(None),
                Approval.deleted_at.is_(None),
            )
        )
        return {stage: user_id for stage, user_id in rows if user_id is not None}

    async def _apply_material_submission_decision(
        self, request: MaterialRequest, approval: Approval, actor: User, decision: str
    ) -> int | None:
        submission = await self.session.get(
            MaterialRequestSubmission, (request.id, approval.submission_revision)
        )
        if submission is None or not await self._material_stage_is_open(approval):
            raise AppException(
                "The material submission is no longer at this review stage.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        stages = frozen_material_stages(submission)
        stage = approval.step_order
        if stage not in stages:
            raise AppException(
                "This review stage is not required.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        earlier = await self._material_deciders(request.id, submission.submission_revision, stage)
        if set(earlier) != set(stages[: stages.index(stage)]) or actor.id in earlier.values():
            raise AppException(
                "Engineer verification is required before manager approval."
                if stage == 2
                else "Independent approval at every earlier stage is required.",
                status_code=409,
                error_code="REQUEST_STATUS_INVALID",
            )
        role = MATERIAL_STAGE_ROLES[stage]
        if stage in (1, 2):
            await self.require_project_reviewer(
                request.project_id,
                role,
                approver_id=actor.id,
                excluded_user_ids={submission.submitted_by},
            )
        elif not await self.session.scalar(
            select(User.id).where(
                User.id == actor.id,
                User.role == role,
                User.is_active.is_(True),
                User.deleted_at.is_(None),
                User.id != submission.submitted_by,
            )
        ):
            raise AppException(
                "This director is not eligible to decide the stage.",
                status_code=403,
                error_code="APPROVAL_FORBIDDEN",
            )
        request.revision += 1
        if decision != "approved":
            request.status = decision
            return None
        if stage != stages[-1]:
            next_stage = stages[stages.index(stage) + 1]
            request.status = MATERIAL_STAGE_STATES[next_stage]
            await self.create_approval(
                ApprovalCreateRequest(
                    request_type="material_request",
                    request_id=request.id,
                    project_id=request.project_id,
                    title=f"{request.request_number} · {MATERIAL_STAGE_TITLES[next_stage]}",
                    amount=(
                        request.total_estimated_cost
                        if isinstance(submission.requirements, dict)
                        and (
                            submission.requirements.get("valuation_status") == "complete"
                            or submission.requirements.get("valuation_complete") is True
                        )
                        else None
                    ),
                ),
                actor,
                commit=False,
                internal=True,
                material_submission=submission,
                step_order=next_stage,
            )
            return next_stage
        request.status = "approved"
        if submission.processor_id is not None:
            await self.notifications.create(
                user_id=submission.processor_id,
                title=MATERIAL_FULFILLMENT_TITLE,
                body=append_link(
                    f"{request.request_number} is ready for fulfillment.",
                    label="Open material request",
                    url=material_request_url(request.id),
                ),
                notification_type="inventory",
                reference_type="approvals",
                reference_id=approval.id,
            )
        return None

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
