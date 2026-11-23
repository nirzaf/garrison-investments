from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.photo import Photo
from app.models.project import Project
from app.models.supervisor_update import SupervisorUpdate, SupervisorUpdateSubmission
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.supervisor_update_repository import SupervisorUpdateRepository
from app.schemas.supervisor_updates import (
    SupervisorUpdateCreateRequest,
    SupervisorUpdateDecisionRequest,
    SupervisorUpdateResponse,
)
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids, ensure_entity_access
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.links import append_link, build_frontend_url
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    OFFICIAL_REPORT_AUTHOR_ROLES,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    ROLE_MEP_PROJECT_MANAGER,
    ROLE_QUANTITY_SURVEYOR,
    SUPERVISOR_ROLES,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now
from app.utils.time import business_today

SUPERVISOR_UPDATE_STATUSES = {
    "draft",
    "submitted",
    "pending_qs",
    "pending_engineer",
    "returned",
    "verified",
    "rejected",
}


class ReportingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectRepository(session)
        self.updates = SupervisorUpdateRepository(session)
        self.audit = AuditService(session)

    async def describe_updates(
        self, updates: list[SupervisorUpdate]
    ) -> list[SupervisorUpdateResponse]:
        verifier_ids = {update.verified_by for update in updates if update.verified_by is not None}
        names: dict[UUID, str] = {}
        if verifier_ids:
            result = await self.session.execute(
                select(User.id, User.full_name).where(User.id.in_(verifier_ids))
            )
            names = {user_id: full_name for user_id, full_name in result}
        reviewers = (
            {
                row.update_id: row
                for row in await self.session.scalars(
                    select(SupervisorUpdateSubmission)
                    .join(
                        SupervisorUpdate,
                        SupervisorUpdate.id == SupervisorUpdateSubmission.update_id,
                    )
                    .where(
                        SupervisorUpdate.id.in_([update.id for update in updates]),
                        SupervisorUpdate.submission_revision
                        == SupervisorUpdateSubmission.submission_revision,
                    )
                )
            }
            if updates
            else {}
        )
        return [
            SupervisorUpdateResponse.model_validate(update).model_copy(
                update={
                    "verified_by_name": names.get(update.verified_by)
                    if update.verified_by is not None
                    else None,
                    "pending_reviewer_id": self._pending_reviewer(update, reviewers.get(update.id)),
                }
            )
            for update in updates
        ]

    @staticmethod
    def _pending_reviewer(
        update: SupervisorUpdate, submission: SupervisorUpdateSubmission | None
    ) -> UUID | None:
        if submission is None:
            return None
        if update.status == "pending_qs":
            return submission.qs_id
        if update.status == "pending_engineer":
            return submission.engineer_id
        return None

    async def create_supervisor_update(
        self,
        payload: SupervisorUpdateCreateRequest,
        actor: User,
    ) -> SupervisorUpdate:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        if actor.role not in SUPERVISOR_ROLES:
            raise AppException(
                "Only site supervisors can create supervisor updates.",
                status_code=403,
                error_code="SUPERVISOR_UPDATE_FORBIDDEN",
            )
        await self._ensure_project_member(payload.project_id, actor)
        self._validate_day_type(payload.day_type)
        self._validate_previous_date(payload, actor)
        update = SupervisorUpdate(
            project_id=payload.project_id,
            supervisor_id=actor.id,
            update_date=payload.update_date,
            day_type=payload.day_type,
            work_location=payload.work_location,
            attendance_count=payload.attendance_count,
            overtime_hours=payload.overtime_hours,
            progress_notes=payload.progress_notes,
            delay_notes=payload.delay_notes,
            required_notes=payload.required_notes,
            attachment_refs=[ref.model_dump() for ref in payload.attachment_refs],
            status="draft",
        )
        self._update_progress_fields(update, payload)
        try:
            await self.updates.add(update)
            await self.audit.record(
                action="supervisor_updates.created",
                user_id=actor.id,
                entity_type="supervisor_updates",
                entity_id=update.id,
                new_values={"project_id": str(update.project_id), "date": str(update.update_date)},
            )
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "You already have a draft or submitted update for this project date.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_EXISTS",
            ) from exc
        return update

    async def update_supervisor_update(
        self,
        update_id: UUID,
        payload: SupervisorUpdateCreateRequest,
        actor: User,
    ) -> SupervisorUpdate:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        if actor.role not in SUPERVISOR_ROLES:
            raise AppException(
                "This role cannot edit supervisor updates.",
                status_code=403,
                error_code="SUPERVISOR_UPDATE_FORBIDDEN",
            )
        update = await self.updates.get_by_id(update_id, for_update=True)
        if not update:
            raise NotFoundException("Supervisor update")
        if update.supervisor_id != actor.id:
            raise NotFoundException("Supervisor update")
        legacy = update.status == "submitted" and update.submission_revision is None
        correcting = update.status in {"returned", "rejected"} or legacy
        if update.status != "draft" and not correcting:
            raise AppException(
                "Only drafts or returned site updates can be edited.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_LOCKED",
            )
        if correcting or payload.expected_revision is not None or update.submission_revision:
            self._check_draft_revision(update, payload.expected_revision)
        if (correcting or update.submission_revision) and (
            update.project_id != payload.project_id or update.update_date != payload.update_date
        ):
            raise AppException(
                "A corrected update must keep its original project and reporting date.",
                status_code=422,
                error_code="SUPERVISOR_CORRECTION_SCOPE_INVALID",
            )
        await self._ensure_project_member(payload.project_id, actor)
        self._validate_day_type(payload.day_type)
        if not correcting and update.submission_revision is None:
            self._validate_previous_date(payload, actor)
        if update.project_id != payload.project_id and await self.session.scalar(
            select(Photo.id)
            .where(
                Photo.entity_type == "supervisor_update",
                Photo.entity_id == update.id,
                Photo.deleted_at.is_(None),
            )
            .limit(1)
        ):
            raise AppException(
                "Remove the draft's uploaded files before changing its project.",
                status_code=409,
                error_code="SUPERVISOR_EVIDENCE_PROJECT_LOCKED",
            )
        update.project_id = payload.project_id
        update.update_date = payload.update_date
        update.day_type = payload.day_type
        update.work_location = payload.work_location
        update.attendance_count = payload.attendance_count
        update.overtime_hours = payload.overtime_hours
        update.progress_notes = payload.progress_notes
        update.delay_notes = payload.delay_notes
        update.required_notes = payload.required_notes
        update.attachment_refs = [ref.model_dump() for ref in payload.attachment_refs]
        self._update_progress_fields(update, payload)
        update.status = "draft"
        update.revision += 1
        await self.audit.record(
            action="supervisor_updates.autosaved",
            user_id=actor.id,
            entity_type="supervisor_updates",
            entity_id=update.id,
            new_values={"project_id": str(update.project_id), "date": str(update.update_date)},
        )
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "You already have a draft or submitted update for this project date.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_EXISTS",
            ) from exc
        return update

    @staticmethod
    def _update_progress_fields(
        update: SupervisorUpdate, payload: SupervisorUpdateCreateRequest
    ) -> None:
        update.activity_scope = (payload.activity_scope or "").strip() or None
        update.remaining_work = (payload.remaining_work or "").strip() or None
        update.completed_area = (payload.completed_area or "").strip() or None
        update.completed_quantity = payload.completed_quantity
        update.quantity_unit = (payload.quantity_unit or "").strip() or None
        update.progress_percentage = payload.progress_percentage

    @staticmethod
    def _check_draft_revision(update: SupervisorUpdate, expected: int | None) -> None:
        if update.revision != expected:
            raise AppException(
                "Reload the site update before making further changes.",
                status_code=409,
                error_code="SITE_UPDATE_REVISION_CONFLICT",
            )

    async def submit_supervisor_update(
        self, update_id: UUID, actor: User, expected_revision: int
    ) -> SupervisorUpdate:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        if actor.role not in SUPERVISOR_ROLES:
            raise PermissionDeniedException("submit site progress")
        update = await self.updates.get_by_id(update_id, for_update=True)
        if not update or update.supervisor_id != actor.id:
            raise NotFoundException("Supervisor update")
        self._check_draft_revision(update, expected_revision)
        if update.status != "draft":
            raise AppException(
                "Only draft updates can be submitted.",
                status_code=409,
                error_code="SUPERVISOR_UPDATE_LOCKED",
            )
        await self._ensure_project_member(update.project_id, actor)
        await self._ensure_active_project(update.project_id)
        if (
            not update.activity_scope
            or not update.remaining_work
            or not update.progress_notes.strip()
        ):
            raise AppException(
                "Enter work scope, completed work and remaining work before submitting.",
                status_code=422,
                error_code="SITE_PROGRESS_DETAILS_REQUIRED",
            )
        photos = list(
            await self.session.scalars(
                select(Photo.id)
                .where(
                    Photo.entity_type == "supervisor_update",
                    Photo.entity_id == update.id,
                    Photo.kind == "photo",
                    Photo.uploaded_by == actor.id,
                    Photo.deleted_at.is_(None),
                    Photo.processing_status == "ready",
                )
                .order_by(Photo.created_at, Photo.id)
            )
        )
        if not photos:
            raise AppException(
                "Upload at least one photograph before submitting site progress.",
                status_code=422,
                error_code="SITE_PROGRESS_PHOTO_REQUIRED",
            )
        reviewers = ApprovalService(self.session)
        engineer = await reviewers.require_project_reviewer(
            update.project_id, ROLE_MEP_PROJECT_MANAGER, excluded_user_ids={actor.id}
        )
        qs = None
        if update.completed_quantity is not None or update.completed_area:
            qs = await reviewers.require_project_reviewer(
                update.project_id, ROLE_QUANTITY_SURVEYOR, excluded_user_ids={actor.id, engineer.id}
            )
        update.submission_revision = (update.submission_revision or 0) + 1
        update.revision += 1
        update.status = "pending_qs" if qs else "pending_engineer"
        update.submitted_at = utc_now()
        snapshot = SupervisorUpdateCreateRequest.model_validate(update, from_attributes=True)
        self.session.add(
            SupervisorUpdateSubmission(
                update_id=update.id,
                submission_revision=update.submission_revision,
                requirements=snapshot.model_dump(mode="json", exclude={"expected_revision"}),
                evidence_ids=[str(photo) for photo in photos],
                engineer_id=engineer.id,
                qs_id=qs.id if qs else None,
            )
        )
        await self.audit.record(
            action="supervisor_updates.submitted",
            user_id=actor.id,
            entity_type="supervisor_updates",
            entity_id=update.id,
            new_values={
                "submission_revision": update.submission_revision,
                "status": update.status,
            },
        )
        await self._notify(
            update,
            qs.id if qs else engineer.id,
            "Site progress awaiting review",
            "Review the submitted progress and photographs.",
        )
        await self.session.commit()
        return update

    async def review_supervisor_update(
        self, update_id: UUID, payload: SupervisorUpdateDecisionRequest, actor: User
    ) -> SupervisorUpdate:
        role = ROLE_QUANTITY_SURVEYOR if payload.stage == "qs" else ROLE_MEP_PROJECT_MANAGER
        if actor.role != role:
            raise PermissionDeniedException("perform this progress review")
        update = await self.updates.get_by_id(update_id, for_update=True)
        if update is None:
            raise NotFoundException("Supervisor update")
        await ensure_entity_access(self.session, "supervisor_update", update.id, actor)
        submission = await self.session.get(
            SupervisorUpdateSubmission, (update.id, update.submission_revision)
        )
        if submission is None or update.submission_revision != payload.expected_submission_revision:
            raise AppException(
                "Reload the submitted progress before deciding.",
                status_code=409,
                error_code="SUBMISSION_REVISION_CONFLICT",
            )
        if self._pending_reviewer(update, submission) != actor.id:
            raise PermissionDeniedException("review this supervisor submission")
        if update.status != f"pending_{payload.stage}":
            raise AppException(
                "This review stage is no longer open.",
                status_code=409,
                error_code="SUPERVISOR_REVIEW_STAGE_INVALID",
            )
        await self._ensure_active_project(update.project_id)
        await ApprovalService(self.session).require_project_reviewer(
            update.project_id,
            role,
            approver_id=actor.id,
            excluded_user_ids={update.supervisor_id},
        )
        comments = (payload.comments or "").strip() or None
        if payload.decision != "approved" and comments is None:
            raise AppException(
                "Give a reason for returning or rejecting progress.",
                status_code=422,
                error_code="DECISION_REASON_REQUIRED",
            )
        now = utc_now()
        if payload.stage == "qs":
            submission.qs_decision = payload.decision
            submission.qs_decided_at = now
            submission.qs_comments = comments
        else:
            if submission.qs_id is not None and (
                submission.qs_decision != "approved" or submission.qs_decided_at is None
            ):
                raise AppException(
                    "Independent QS confirmation is required.",
                    status_code=409,
                    error_code="QS_REVIEW_REQUIRED",
                )
            submission.engineer_decision = payload.decision
            submission.engineer_decided_at = now
            submission.engineer_comments = comments
        if payload.decision != "approved":
            update.status = payload.decision
            await self._notify(
                update, update.supervisor_id, f"Site progress {update.status}", comments or ""
            )
        elif payload.stage == "qs":
            update.status = "pending_engineer"
            await self._notify(
                update,
                submission.engineer_id,
                "Site progress awaiting technical confirmation",
                "The independent quantity and area check is complete.",
            )
        else:
            update.status = "verified"
            update.verified_by = actor.id
            update.verified_at = now
            update.verification_notes = comments
            await self._notify(
                update,
                update.supervisor_id,
                "Site progress confirmed",
                "The independent technical review is complete.",
            )
        update.revision += 1
        await self.audit.record(
            action=f"supervisor_updates.review.{payload.stage}.{payload.decision}",
            user_id=actor.id,
            entity_type="supervisor_updates",
            entity_id=update.id,
            comments=comments,
            new_values={"submission_revision": update.submission_revision, "status": update.status},
        )
        await self.session.commit()
        return update

    async def supervisor_submission_history(
        self, update_id: UUID, actor: User
    ) -> list[SupervisorUpdateSubmission]:
        await ensure_entity_access(self.session, "supervisor_update", update_id, actor)
        query = select(SupervisorUpdateSubmission).where(
            SupervisorUpdateSubmission.update_id == update_id
        )
        if actor.role == ROLE_QUANTITY_SURVEYOR:
            query = query.where(SupervisorUpdateSubmission.qs_id == actor.id)
        return list(
            await self.session.scalars(
                query.order_by(SupervisorUpdateSubmission.submission_revision.desc())
            )
        )

    async def _ensure_active_project(self, project_id: UUID) -> None:
        if not await self.session.scalar(
            select(Project.id)
            .where(
                Project.id == project_id, Project.status == "active", Project.deleted_at.is_(None)
            )
            .with_for_update(read=True)
        ):
            raise NotFoundException("Active project")

    async def _notify(self, update: SupervisorUpdate, user_id: UUID, title: str, body: str) -> None:
        await NotificationService(self.session).create(
            user_id=user_id,
            title=title,
            body=append_link(
                body,
                label="Open site progress",
                url=build_frontend_url(
                    "/reports/supervisor-update", query={"updateId": str(update.id)}
                ),
            ),
            notification_type="report",
            reference_type="supervisor_update",
            reference_id=update.id,
        )

    async def list_supervisor_updates(
        self,
        *,
        current_user: User,
        project_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
        review_only: bool = False,
        update_id: UUID | None = None,
    ) -> tuple[list[SupervisorUpdate], int]:
        self._validate_status(status)
        is_supervisor = current_user.role in SUPERVISOR_ROLES
        supervisor_id = current_user.id if is_supervisor else None
        project_ids: list[UUID] | None = None
        reviewer_id = None
        if review_only and current_user.role == ROLE_QUANTITY_SURVEYOR:
            project_ids = await accessible_project_ids(self.session, current_user) or []
            reviewer_id = current_user.id
        elif is_supervisor:
            project_ids = await self.projects.list_project_ids_for_user(current_user.id)
            if project_id is not None:
                await self._ensure_project_member(project_id, current_user)
            elif not project_ids:
                return [], 0
        elif (
            current_user.role in OFFICIAL_REPORT_AUTHOR_ROLES
            and has_permission(current_user, PERMISSION_REPORTS_SUBMIT)
            and not has_permission(current_user, PERMISSION_REPORTS_VIEW)
        ):
            # Keep official report evidence selection project-explicit and confirmed-only.
            if project_id is None:
                raise AppException(
                    "Choose an assigned project to view confirmed supervisor updates.",
                    status_code=422,
                    error_code="SUPERVISOR_UPDATE_PROJECT_REQUIRED",
                )
            await self._ensure_project_member(project_id, current_user)
            status = "verified"
        elif (
            has_permission(current_user, PERMISSION_REPORTS_VIEW)
            and current_user.role not in COMPANY_RESOURCE_ROLES
        ):
            if project_id is not None:
                await self._ensure_project_member(project_id, current_user)
            else:
                project_ids = await accessible_project_ids(self.session, current_user) or []
        elif current_user.role not in COMPANY_RESOURCE_ROLES and not is_supervisor:
            raise AppException(
                "You do not have access to supervisor updates.",
                status_code=403,
                error_code="SUPERVISOR_UPDATE_FORBIDDEN",
            )
        return await self.updates.list_updates(
            project_id=project_id,
            supervisor_id=supervisor_id,
            status=status,
            limit=min(limit, 200),
            offset=max(offset, 0),
            project_ids=project_ids,
            qs_reviewer_id=reviewer_id,
            update_id=update_id,
        )

    async def _ensure_project_member(self, project_id: UUID, actor: User) -> None:
        project = await self.projects.get_by_id(project_id)
        if not project:
            raise NotFoundException("Project")
        if actor.role in COMPANY_RESOURCE_ROLES:
            return
        members = await self.projects.list_members(project_id)
        if not any(member.user_id == actor.id for member in members):
            raise NotFoundException("Project")

    def _validate_previous_date(self, payload: SupervisorUpdateCreateRequest, actor: User) -> None:
        is_previous_date = payload.update_date < (business_today() - timedelta(days=1))
        if is_previous_date:
            raise AppException(
                "Previous-date supervisor updates are not supported.",
                status_code=409,
                error_code="PREVIOUS_DATE_UPDATE_UNSUPPORTED",
            )

    def _validate_day_type(self, day_type: str) -> None:
        if day_type not in {"weekday", "friday", "public_holiday"}:
            raise AppException("Invalid day type.", status_code=422, error_code="INVALID_DAY_TYPE")

    def _validate_status(self, status: str | None) -> None:
        if status and status not in SUPERVISOR_UPDATE_STATUSES:
            raise AppException(
                "Invalid supervisor update status.",
                status_code=422,
                error_code="INVALID_SUPERVISOR_UPDATE_STATUS",
            )
