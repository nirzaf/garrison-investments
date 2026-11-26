from datetime import date, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrAccessRequest,
    HrDepartment,
    HrDocument,
    HrDocumentVersion,
    HrEmployee,
    HrEmployeePrivate,
    HrEmploymentChange,
    HrEmploymentHistory,
    HrEmploymentPeriod,
    HrLeaveRequest,
    HrOffboardingCase,
    HrOnboardingCase,
    HrPosition,
)
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.schemas.hr import (
    AccessRequestCreateRequest,
    AccessRequestDecisionRequest,
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
    DueEmploymentChange,
    DueEmploymentChangeList,
    EmployeeCreateRequest,
    EmployeeDetailResponse,
    EmployeeDirectoryResponse,
    EmployeeLinkAccountRequest,
    EmployeeManagerReviewRequest,
    EmployeePrivateUpdateRequest,
    EmployeeSelfResponse,
    EmployeeSelfUpdateRequest,
    EmployeeSensitiveResponse,
    EmployeeStatusTransitionRequest,
    EmployeeUpdateRequest,
    EmploymentChangeDecision,
    EmploymentChangeFields,
    EmploymentChangeListResponse,
    EmploymentChangeProposal,
    EmploymentChangeResponse,
    EmploymentPeriodMissingStart,
    EmploymentPeriodMissingStartPage,
    HrEmployeeDataQualityIssue,
    HrEmployeeDataQualityPage,
    OnboardingCaseResponse,
    OrgChartNode,
    OrgChartResponse,
    PositionCreateRequest,
    PositionUpdateRequest,
    ProbationReviewRequest,
)
from app.schemas.users import UserCreateRequest, UserUpdateRequest
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value, mask_identifier
from app.services.hr_manager_review import eligible_reviewer
from app.services.hr_offboarding_custody import confirmed_access_revocation
from app.services.hr_payroll_snapshot import lock_payroll_periods
from app.services.hr_project_assignment import ACTIVE_ASSIGNMENT_EMPLOYMENT
from app.services.hr_workforce_service import HrWorkforceService
from app.services.user_service import UserService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    BUSINESS_ROLES,
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_OFFBOARDING_MANAGE,
    PERMISSION_HR_ONBOARDING_MANAGE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_POLICY_MANAGE,
    PERMISSION_USERS_MANAGE,
    ensure_permission,
    has_permission,
    validate_role,
)
from app.utils.security import utc_now
from app.utils.time import business_today


class HrService(HrWorkforceService):
    """Facade for HR organization, master directory, private vault, access requests, and ops."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # --- Departments & Positions (HR-004) ---

    async def create_department(
        self, payload: DepartmentCreateRequest, actor: User
    ) -> HrDepartment:
        dept = HrDepartment(**payload.model_dump())
        self.session.add(dept)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.department.created",
                user_id=actor.id,
                entity_type="hr_departments",
                entity_id=dept.id,
                new_values={"code": dept.code, "name": dept.name},
            )
            await self.session.commit()
            await self.session.refresh(dept)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Department code already exists.",
                status_code=409,
                error_code="DEPARTMENT_EXISTS",
            ) from exc
        return dept

    async def update_department(
        self, dept_id: UUID, payload: DepartmentUpdateRequest, actor: User
    ) -> HrDepartment:
        dept = await self.session.scalar(
            select(HrDepartment).where(
                HrDepartment.id == dept_id, HrDepartment.deleted_at.is_(None)
            )
        )
        if dept is None:
            raise NotFoundException("Department")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(dept, key, value)
        await self.audit.record(
            action="hr.department.updated",
            user_id=actor.id,
            entity_type="hr_departments",
            entity_id=dept.id,
        )
        await self._commit_and_refresh(dept)
        return dept

    async def list_departments(self) -> tuple[list[HrDepartment], int]:
        rows = list(
            await self.session.scalars(
                select(HrDepartment)
                .where(HrDepartment.deleted_at.is_(None))
                .order_by(HrDepartment.code.asc())
            )
        )
        return rows, len(rows)

    async def create_position(self, payload: PositionCreateRequest, actor: User) -> HrPosition:
        pos = HrPosition(**payload.model_dump())
        self.session.add(pos)
        try:
            await self.session.flush()
            await self.audit.record(
                action="hr.position.created",
                user_id=actor.id,
                entity_type="hr_positions",
                entity_id=pos.id,
                new_values={"code": pos.code, "title": pos.title},
            )
            await self.session.commit()
            await self.session.refresh(pos)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Position code already exists.",
                status_code=409,
                error_code="POSITION_EXISTS",
            ) from exc
        return pos

    async def update_position(
        self, pos_id: UUID, payload: PositionUpdateRequest, actor: User
    ) -> HrPosition:
        pos = await self.session.scalar(
            select(HrPosition).where(HrPosition.id == pos_id, HrPosition.deleted_at.is_(None))
        )
        if pos is None:
            raise NotFoundException("Position")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(pos, key, value)
        await self.audit.record(
            action="hr.position.updated",
            user_id=actor.id,
            entity_type="hr_positions",
            entity_id=pos.id,
        )
        await self._commit_and_refresh(pos)
        return pos

    async def list_positions(self) -> tuple[list[HrPosition], int]:
        rows = list(
            await self.session.scalars(
                select(HrPosition)
                .where(HrPosition.deleted_at.is_(None))
                .order_by(HrPosition.code.asc())
            )
        )
        return rows, len(rows)

    async def get_org_chart(self) -> OrgChartResponse:
        employees = list(
            await self.session.scalars(
                select(HrEmployee)
                .where(
                    HrEmployee.deleted_at.is_(None),
                    HrEmployee.employment_status != "archived",
                )
                .order_by(HrEmployee.employee_code.asc())
            )
        )
        depts = {
            d.id: d.name
            for d in await self.session.scalars(
                select(HrDepartment).where(HrDepartment.deleted_at.is_(None))
            )
        }
        positions = {
            p.id: p.title
            for p in await self.session.scalars(
                select(HrPosition).where(HrPosition.deleted_at.is_(None))
            )
        }
        active_primary_assignments = set(
            await self.session.scalars(
                select(HrEmployee.id)
                .join(Project, Project.id == HrEmployee.primary_project_id)
                .join(User, User.id == HrEmployee.user_id)
                .join(
                    ProjectMember,
                    (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == User.id),
                )
                .where(
                    HrEmployee.deleted_at.is_(None),
                    HrEmployee.employment_status.in_(ACTIVE_ASSIGNMENT_EMPLOYMENT),
                    Project.deleted_at.is_(None),
                    ProjectMember.deleted_at.is_(None),
                    User.deleted_at.is_(None),
                    User.is_active.is_(True),
                )
            )
        )
        nodes: dict[UUID, OrgChartNode] = {
            emp.id: OrgChartNode(
                employee_id=emp.id,
                employee_code=emp.employee_code,
                full_name=emp.full_name,
                employment_status=emp.employment_status,
                department_id=emp.department_id,
                department_name=depts.get(emp.department_id) if emp.department_id else None,
                position_id=emp.position_id,
                position_title=positions.get(emp.position_id) if emp.position_id else None,
                manager_employee_id=emp.manager_employee_id,
                work_location=emp.work_location,
                primary_assignment=(
                    "active"
                    if emp.id in active_primary_assignments
                    else "inactive"
                    if emp.primary_project_id
                    else "none"
                ),
                direct_reports=[],
            )
            for emp in employees
        }
        roots: list[OrgChartNode] = []
        for node in nodes.values():
            if node.manager_employee_id and node.manager_employee_id in nodes:
                nodes[node.manager_employee_id].direct_reports.append(node)
            else:
                roots.append(node)
        return OrgChartResponse(roots=roots, total_employees=len(employees))

    # --- Employee Master Directory & History (HR-002, HR-003) ---

    async def _check_position_headcount(
        self, position_id: UUID, *, exclude_employee_id: UUID | None, override: bool, actor: User
    ) -> None:
        pos = await self.session.scalar(
            select(HrPosition)
            .where(HrPosition.id == position_id, HrPosition.deleted_at.is_(None))
            .with_for_update()
        )
        if pos is None:
            raise NotFoundException("Position")
        stmt = select(func.count(HrEmployee.id)).where(
            HrEmployee.position_id == position_id,
            HrEmployee.deleted_at.is_(None),
            HrEmployee.employment_status.notin_(["terminated", "resigned", "archived"]),
        )
        if exclude_employee_id is not None:
            stmt = stmt.where(HrEmployee.id != exclude_employee_id)
        filled = int(await self.session.scalar(stmt) or 0)
        if filled >= pos.headcount_limit:
            if override:
                if not has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE):
                    raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
                return
            raise AppException(
                f"Headcount limit ({pos.headcount_limit}) reached for position '{pos.title}'.",
                status_code=409,
                error_code="HEADCOUNT_LIMIT_EXCEEDED",
            )

    async def _validate_manager_assignment(
        self, employee_id: UUID | None, manager_employee_id: UUID | None
    ) -> None:
        if manager_employee_id is None:
            return
        if employee_id is not None and manager_employee_id == employee_id:
            raise AppException(
                "An employee cannot be assigned as their own manager.",
                status_code=422,
                error_code="MANAGER_CYCLE_DETECTED",
            )
        mgr = await self._require_employee(manager_employee_id)
        if employee_id is None:
            return
        visited: set[UUID] = {employee_id}
        cursor: UUID | None = mgr.id
        steps = 0
        while cursor is not None and steps < 200:
            if cursor in visited:
                raise AppException(
                    "Reporting hierarchy cycle detected.",
                    status_code=422,
                    error_code="MANAGER_CYCLE_DETECTED",
                )
            visited.add(cursor)
            next_mgr = await self.session.scalar(
                select(HrEmployee.manager_employee_id).where(HrEmployee.id == cursor)
            )
            cursor = next_mgr
            steps += 1

    def _employee_snapshot(self, emp: HrEmployee) -> dict[str, object]:
        return {
            "employee_code": emp.employee_code,
            "full_name": emp.full_name,
            "work_email": emp.work_email,
            "employment_status": emp.employment_status,
            "employment_category": emp.employment_category,
            "department_id": str(emp.department_id) if emp.department_id else None,
            "position_id": str(emp.position_id) if emp.position_id else None,
            "primary_project_id": str(emp.primary_project_id) if emp.primary_project_id else None,
            "manager_employee_id": (
                str(emp.manager_employee_id) if emp.manager_employee_id else None
            ),
            "work_location": emp.work_location,
        }

    async def _serialize_employee_detail(self, emp: HrEmployee) -> EmployeeDetailResponse:
        dept_name: str | None = None
        pos_title: str | None = None
        if emp.department_id:
            dept_name = await self.session.scalar(
                select(HrDepartment.name).where(HrDepartment.id == emp.department_id)
            )
        if emp.position_id:
            pos_title = await self.session.scalar(
                select(HrPosition.title).where(HrPosition.id == emp.position_id)
            )
        return EmployeeDetailResponse(
            id=emp.id,
            employee_code=emp.employee_code,
            first_name=emp.first_name,
            last_name=emp.last_name,
            preferred_name=emp.preferred_name,
            full_name=emp.full_name,
            work_email=emp.work_email,
            work_phone=emp.work_phone,
            employment_status=emp.employment_status,
            employment_category=emp.employment_category,
            join_date=emp.join_date,
            confirmation_date=emp.confirmation_date,
            termination_date=emp.termination_date,
            department_id=emp.department_id,
            department_name=dept_name,
            position_id=emp.position_id,
            position_title=pos_title,
            primary_project_id=emp.primary_project_id,
            manager_employee_id=emp.manager_employee_id,
            work_location=emp.work_location,
            work_calendar_id=emp.work_calendar_id,
            line_manager_reviewer_id=emp.line_manager_reviewer_id,
            user_id=emp.user_id,
            record_revision=emp.record_revision,
            created_at=emp.created_at,
            updated_at=emp.updated_at,
        )

    async def create_employee(
        self, payload: EmployeeCreateRequest, actor: User
    ) -> EmployeeDetailResponse:
        if payload.employment_status not in {"draft", "active", "on_probation"}:
            raise AppException("Create a draft or a current employee.", status_code=422)
        if payload.employment_status != "draft" and not has_permission(
            actor, PERMISSION_HR_EMPLOYEES_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if not payload.first_name.strip() or not payload.last_name.strip():
            raise AppException("First and last names are required.", status_code=422)
        if payload.manager_employee_id:
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_reporting_lines'))")
            )
        if payload.position_id:
            await self._check_position_headcount(
                payload.position_id,
                exclude_employee_id=None,
                override=payload.override_headcount,
                actor=actor,
            )
        await self._validate_manager_assignment(None, payload.manager_employee_id)
        full_name = (
            payload.full_name.strip()
            if payload.full_name
            else f"{payload.first_name.strip()} {payload.last_name.strip()}"
        )
        emp = HrEmployee(
            employee_code=payload.employee_code.strip(),
            first_name=payload.first_name.strip(),
            last_name=payload.last_name.strip(),
            preferred_name=payload.preferred_name.strip() if payload.preferred_name else None,
            full_name=full_name,
            work_email=payload.work_email.lower() if payload.work_email else None,
            work_phone=payload.work_phone.strip() if payload.work_phone else None,
            employment_status=payload.employment_status,
            employment_category=payload.employment_category,
            join_date=payload.join_date,
            confirmation_date=payload.confirmation_date,
            department_id=payload.department_id,
            position_id=payload.position_id,
            primary_project_id=payload.primary_project_id,
            manager_employee_id=payload.manager_employee_id,
            work_location=payload.work_location,
            work_calendar_id=payload.work_calendar_id,
            record_revision=1,
            created_by_id=actor.id,
            updated_by_id=actor.id,
        )
        self.session.add(emp)
        try:
            await self.session.flush()
            self.session.add(
                HrEmploymentHistory(
                    employee_id=emp.id,
                    change_type="created",
                    effective_date=emp.join_date or utc_now().date(),
                    previous_snapshot=None,
                    new_snapshot=self._employee_snapshot(emp),
                    reason=payload.reason or "Initial employee record creation",
                    actor_user_id=actor.id,
                )
            )
            await self.audit.record(
                action="hr.employee.created",
                user_id=actor.id,
                entity_type="hr_employees",
                entity_id=emp.id,
                new_values={"employee_code": emp.employee_code, "status": emp.employment_status},
            )
            await self.session.commit()
            await self.session.refresh(emp)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "An employee with this code or work email already exists.",
                status_code=409,
                error_code="EMPLOYEE_CONFLICT",
            ) from exc
        return await self._serialize_employee_detail(emp)

    async def list_employees(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EmployeeDirectoryResponse], int]:
        stmt = select(HrEmployee).where(HrEmployee.deleted_at.is_(None))
        count_stmt = select(func.count(HrEmployee.id)).where(HrEmployee.deleted_at.is_(None))
        if search:
            like = f"%{search.strip()}%"
            filt = or_(
                HrEmployee.full_name.ilike(like),
                HrEmployee.employee_code.ilike(like),
                HrEmployee.work_email.ilike(like),
            )
            stmt = stmt.where(filt)
            count_stmt = count_stmt.where(filt)
        if status:
            stmt = stmt.where(HrEmployee.employment_status == status)
            count_stmt = count_stmt.where(HrEmployee.employment_status == status)
        if department_id:
            stmt = stmt.where(HrEmployee.department_id == department_id)
            count_stmt = count_stmt.where(HrEmployee.department_id == department_id)

        rows = list(
            await self.session.scalars(
                stmt.order_by(HrEmployee.employee_code.asc()).limit(min(limit, 200)).offset(offset)
            )
        )
        total = int(await self.session.scalar(count_stmt) or 0)
        depts = {
            d.id: d.name
            for d in await self.session.scalars(
                select(HrDepartment).where(HrDepartment.deleted_at.is_(None))
            )
        }
        positions = {
            p.id: p.title
            for p in await self.session.scalars(
                select(HrPosition).where(HrPosition.deleted_at.is_(None))
            )
        }
        items = [
            EmployeeDirectoryResponse(
                id=e.id,
                employee_code=e.employee_code,
                full_name=e.full_name,
                preferred_name=e.preferred_name,
                work_email=e.work_email,
                work_phone=e.work_phone,
                employment_status=e.employment_status,
                employment_category=e.employment_category,
                department_id=e.department_id,
                department_name=depts.get(e.department_id) if e.department_id else None,
                position_id=e.position_id,
                position_title=positions.get(e.position_id) if e.position_id else None,
                primary_project_id=e.primary_project_id,
                manager_employee_id=e.manager_employee_id,
                work_location=e.work_location,
                join_date=e.join_date,
            )
            for e in rows
        ]
        return items, total

    async def get_employee_detail(self, employee_id: UUID) -> EmployeeDetailResponse:
        emp = await self._require_employee(employee_id)
        return await self._serialize_employee_detail(emp)

    async def set_employee_manager_review(
        self, employee_id: UUID, payload: EmployeeManagerReviewRequest, actor: User
    ) -> EmployeeDetailResponse:
        if not has_permission(actor, PERMISSION_HR_POLICY_MANAGE):
            raise PermissionDeniedException(PERMISSION_HR_POLICY_MANAGE)
        emp = await self._require_employee(employee_id, for_update=True)
        if emp.record_revision != payload.expected_revision:
            raise AppException(
                "Employee record changed. Reload it first.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        nominated = emp.manager_employee_id if payload.enabled else None
        previous = emp.line_manager_reviewer_id
        if payload.enabled:
            emp.line_manager_reviewer_id = nominated
            if await eligible_reviewer(self.session, emp) is None:
                raise AppException(
                    "Assign an eligible line manager with an active portal account.",
                    status_code=422,
                )
        if nominated == previous:
            return await self._serialize_employee_detail(emp)
        emp.line_manager_reviewer_id = nominated
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        await self.audit.record(
            action="hr.employee.manager_review_updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"enabled": payload.enabled, "revision": emp.record_revision},
        )
        await self._commit_and_refresh(emp)
        return await self._serialize_employee_detail(emp)

    async def update_employee(
        self, employee_id: UUID, payload: EmployeeUpdateRequest, actor: User
    ) -> EmployeeDetailResponse:
        pending_leave: list[HrLeaveRequest] = []
        if "manager_employee_id" in payload.model_fields_set:
            # Match leave-decision lock order: payroll guard, request rows, employee row.
            await lock_payroll_periods(self.session)
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_reporting_lines'))")
            )
            pending_leave = list(
                await self.session.scalars(
                    select(HrLeaveRequest)
                    .where(
                        HrLeaveRequest.employee_id == employee_id,
                        HrLeaveRequest.status == "submitted",
                    )
                    .order_by(HrLeaveRequest.id)
                    .with_for_update()
                )
            )
        emp = await self._require_employee(employee_id, for_update=True)
        previous_manager_id = emp.manager_employee_id
        if emp.employment_status in ACTIVE_ASSIGNMENT_EMPLOYMENT and any(
            name in payload.model_fields_set and getattr(payload, name) != getattr(emp, name)
            for name in ("first_name", "last_name", "full_name")
        ):
            raise AppException(
                "Propose a reviewed profile correction to change this employee's name.",
                status_code=409,
                error_code="PROFILE_CORRECTION_REQUIRED",
            )
        await self._stage_employee_update(emp, payload, actor, "updated", utc_now().date())
        if previous_manager_id != emp.manager_employee_id:
            for leave_request in pending_leave:
                await self._reroute_pending_leave_request(leave_request, emp, actor)
        try:
            await self.session.commit()
            await self.session.refresh(emp)
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppException(
                "Employee work email conflicts with another record.",
                status_code=409,
                error_code="EMPLOYEE_CONFLICT",
            ) from exc
        return await self._serialize_employee_detail(emp)

    async def _stage_employee_update(
        self,
        emp: HrEmployee,
        payload: EmployeeUpdateRequest,
        actor: User,
        change_type: str,
        effective_date: date,
        *,
        contract_history: dict[str, object] | None = None,
    ) -> None:
        if emp.record_revision != payload.expected_revision:
            raise AppException(
                "Employee record has been modified by another user.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        updates = payload.model_dump(
            exclude_unset=True, exclude={"expected_revision", "override_headcount", "reason"}
        )
        if (
            emp.employment_status != "draft"
            and any(
                field in updates
                for field in (
                    "first_name",
                    "last_name",
                    "full_name",
                    "join_date",
                    "confirmation_date",
                    "employment_category",
                )
            )
            and not has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        for field in ("first_name", "last_name", "full_name"):
            if field in updates and not (updates[field] or "").strip():
                raise AppException("Employee names cannot be blank.", status_code=422)
        if "join_date" in updates and updates["join_date"] != emp.join_date:
            if await self.session.scalar(
                select(HrEmploymentPeriod.id)
                .where(HrEmploymentPeriod.employee_id == emp.id)
                .limit(1)
            ):
                raise AppException(
                    "The recorded employment start cannot be edited through the profile.",
                    status_code=409,
                )
        if "employment_category" in updates and updates["employment_category"] is None:
            raise AppException("Choose an employment category.", status_code=422)
        if "employee_code" in updates:
            if not has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE):
                raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
            supplied_code = (updates["employee_code"] or "").strip()
            if not supplied_code or supplied_code.upper().startswith("DRAFT-"):
                raise AppException("Use a verified employee code.", status_code=422)
            updates["employee_code"] = supplied_code
        if emp.user_id and "work_email" in updates and updates["work_email"] != emp.work_email:
            raise AppException(
                "Resolve the portal identity link before changing its work email.", status_code=409
            )
        if "position_id" in updates and updates["position_id"] != emp.position_id:
            if updates["position_id"] is not None:
                await self._check_position_headcount(
                    updates["position_id"],
                    exclude_employee_id=emp.id,
                    override=payload.override_headcount,
                    actor=actor,
                )
        if "manager_employee_id" in updates:
            await self._validate_manager_assignment(emp.id, updates["manager_employee_id"])
            if updates["manager_employee_id"] != emp.manager_employee_id:
                emp.line_manager_reviewer_id = None

        prev = self._employee_snapshot(emp)
        if change_type == "profile_correction":
            prev.update(first_name=emp.first_name, last_name=emp.last_name)
        for field, value in updates.items():
            if field == "work_email" and value is not None:
                value = value.lower()
            setattr(emp, field, value)
        if ("first_name" in updates or "last_name" in updates) and "full_name" not in updates:
            emp.full_name = f"{emp.first_name.strip()} {emp.last_name.strip()}"

        emp.record_revision += 1
        emp.updated_by_id = actor.id
        next_snapshot = {**self._employee_snapshot(emp), **(contract_history or {})}
        if change_type == "profile_correction":
            next_snapshot.update(first_name=emp.first_name, last_name=emp.last_name)
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type=change_type,
                effective_date=effective_date,
                previous_snapshot=prev,
                new_snapshot=next_snapshot,
                reason=payload.reason or "Profile/assignment update",
                actor_user_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.employee.updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"record_revision": emp.record_revision},
        )

    @staticmethod
    def _check_employment_change_base(emp: HrEmployee, revision: int, effective_date: date) -> None:
        if emp.record_revision != revision:
            raise AppException(
                "The employee changed after this proposal. Prepare a fresh proposal.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        if (
            emp.employment_status not in ACTIVE_ASSIGNMENT_EMPLOYMENT
            or (emp.join_date is not None and effective_date < emp.join_date)
            or (emp.termination_date is not None and effective_date >= emp.termination_date)
        ):
            raise AppException(
                "The employee must be in an eligible employment period.", status_code=409
            )

    async def list_employment_periods(
        self, employee_id: UUID, limit: int, offset: int
    ) -> tuple[list[HrEmploymentPeriod], int]:
        await self._require_employee(employee_id)
        filters = (HrEmploymentPeriod.employee_id == employee_id,)
        rows = list(
            await self.session.scalars(
                select(HrEmploymentPeriod)
                .where(*filters)
                .order_by(
                    HrEmploymentPeriod.started_on.desc().nulls_last(), HrEmploymentPeriod.id.desc()
                )
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(select(func.count(HrEmploymentPeriod.id)).where(*filters))
        return rows, total or 0

    async def list_employment_periods_missing_start(
        self, limit: int, offset: int
    ) -> EmploymentPeriodMissingStartPage:
        query = (
            select(
                HrEmploymentPeriod.id.label("period_id"),
                HrEmploymentPeriod.employee_id,
                HrEmployee.employee_code,
                HrEmploymentPeriod.ended_on,
                HrEmploymentPeriod.separation_case_id,
            )
            .join(HrEmployee, HrEmployee.id == HrEmploymentPeriod.employee_id)
            .where(
                HrEmploymentPeriod.started_on.is_(None),
                HrEmploymentPeriod.ended_on.is_not(None),
                HrEmployee.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = (
            await self.session.execute(
                query.order_by(HrEmploymentPeriod.ended_on, HrEmploymentPeriod.id)
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
        return EmploymentPeriodMissingStartPage(
            items=[EmploymentPeriodMissingStart.model_validate(row) for row in rows],
            total=total or 0,
        )

    async def list_employee_data_quality_issues(
        self, limit: int, offset: int
    ) -> HrEmployeeDataQualityPage:
        period_summary = (
            select(
                HrEmploymentPeriod.employee_id.label("employee_id"),
                func.count(HrEmploymentPeriod.id).label("period_count"),
                func.sum(
                    case((HrEmploymentPeriod.ended_on.is_(None), 1), else_=0)
                ).label("open_period_count"),
                func.max(
                    case(
                        (HrEmploymentPeriod.ended_on.is_(None), HrEmploymentPeriod.started_on),
                        else_=None,
                    )
                ).label("open_period_start"),
            )
            .group_by(HrEmploymentPeriod.employee_id)
            .subquery()
        )
        period_count = func.coalesce(period_summary.c.period_count, 0)
        open_period_count = func.coalesce(period_summary.c.open_period_count, 0)
        employment_unverified = or_(
            (period_count > 0)
            & or_(
                open_period_count != 1,
                period_summary.c.open_period_start.is_(None),
                period_summary.c.open_period_start > business_today(),
            ),
            (period_count == 0)
            & or_(HrEmployee.join_date.is_(None), HrEmployee.join_date > business_today()),
        )
        query = (
            select(
                HrEmployee.id,
                HrEmployee.employee_code,
                HrEmployee.full_name,
                HrEmployeePrivate.date_of_birth,
                employment_unverified.label("employment_unverified"),
            )
            .select_from(HrEmployee)
            .outerjoin(HrEmployeePrivate, HrEmployeePrivate.employee_id == HrEmployee.id)
            .outerjoin(period_summary, period_summary.c.employee_id == HrEmployee.id)
            .where(
                HrEmployee.deleted_at.is_(None),
                or_(
                    HrEmployeePrivate.date_of_birth.is_(None),
                    HrEmployeePrivate.date_of_birth > business_today(),
                    employment_unverified,
                ),
            )
        )
        total = int(
            await self.session.scalar(
                select(func.count()).select_from(query.subquery())
            )
            or 0
        )
        rows = (
            await self.session.execute(
                query.order_by(HrEmployee.employee_code, HrEmployee.id)
                .offset(offset)
                .limit(limit)
            )
        ).all()
        items = []
        for employee_id, employee_code, full_name, dob, employment_issue in rows:
            codes: list[
                Literal[
                    "missing_birth_date",
                    "future_birth_date",
                    "employment_start_unverified",
                ]
            ] = []
            if dob is None:
                codes.append("missing_birth_date")
            elif dob > business_today():
                codes.append("future_birth_date")
            if employment_issue:
                codes.append("employment_start_unverified")
            items.append(
                HrEmployeeDataQualityIssue(
                    employee_id=employee_id,
                    employee_code=employee_code,
                    full_name=full_name,
                    issue_codes=codes,
                    required_correction=(
                        "Verify the private HR source record and reconcile employment history."
                    ),
                )
            )
        return HrEmployeeDataQualityPage(
            items=items, total=total, offset=offset, limit=limit
        )

    async def _check_rehire(
        self,
        emp: HrEmployee,
        fields: EmploymentChangeFields,
        revision: int,
        effective_date: date,
        actor: User,
    ) -> HrOffboardingCase:
        ensure_permission(actor, PERMISSION_HR_ONBOARDING_MANAGE)
        ensure_permission(actor, PERMISSION_HR_OFFBOARDING_MANAGE)
        if emp.user_id == actor.id:
            raise PermissionDeniedException("rehire one's own employment record")
        if emp.record_revision != revision:
            raise AppException(
                "The employee changed. Prepare a fresh proposal.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        if emp.employment_status not in {"resigned", "terminated", "archived"}:
            raise AppException("Rehire requires a separated employee.", status_code=409)
        latest = await self.session.scalar(
            select(HrOffboardingCase)
            .where(HrOffboardingCase.employee_id == emp.id, HrOffboardingCase.status == "completed")
            .order_by(
                HrOffboardingCase.completed_at.desc().nulls_last(), HrOffboardingCase.id.desc()
            )
            .limit(1)
        )
        if (
            latest is None
            or latest.id != fields.separation_case_id
            or latest.rehire_eligible is not True
            or emp.termination_date != latest.last_working_date
        ):
            raise AppException(
                "Select the latest completed separation with confirmed rehire eligibility.",
                status_code=409,
            )
        if effective_date <= latest.last_working_date:
            raise AppException(
                "Rehire must start after the prior last working day.", status_code=422
            )
        if emp.join_date is not None and emp.join_date > latest.last_working_date:
            raise AppException("Resolve the prior employment dates before rehire.", status_code=409)
        if emp.user_id:
            await confirmed_access_revocation(self.session, emp)
        if await self.session.scalar(
            select(HrOnboardingCase.id)
            .where(HrOnboardingCase.employee_id == emp.id, HrOnboardingCase.status != "completed")
            .limit(1)
        ):
            raise AppException(
                "Resolve the previous onboarding case before rehire.", status_code=409
            )
        return latest

    async def _apply_rehire(
        self, emp: HrEmployee, row: HrEmploymentChange, fields: EmploymentChangeFields, actor: User
    ) -> None:
        separation = await self._check_rehire(
            emp, fields, row.employee_revision, row.effective_date, actor
        )
        prior = await self.session.scalar(
            select(HrEmploymentPeriod).where(HrEmploymentPeriod.separation_case_id == separation.id)
        )
        if prior is None:
            self.session.add(
                HrEmploymentPeriod(
                    employee_id=emp.id,
                    started_on=emp.join_date,
                    ended_on=separation.last_working_date,
                    separation_case_id=separation.id,
                )
            )
        previous = {
            **self._employee_snapshot(emp),
            "join_date": emp.join_date.isoformat() if emp.join_date else None,
            "termination_date": separation.last_working_date.isoformat(),
            "separation_case_id": str(separation.id),
        }
        emp.employment_status = "onboarding"
        emp.employment_category = fields.employment_category or emp.employment_category
        emp.join_date = row.effective_date
        emp.termination_date = None
        emp.confirmation_date = None
        emp.manager_employee_id = None
        emp.line_manager_reviewer_id = None
        emp.primary_project_id = None
        emp.work_calendar_id = None
        emp.work_location = None
        emp.position_id = None
        emp.department_id = None
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        onboarding = await self._create_onboarding_case_internal(
            employee_id=emp.id,
            offer_id=None,
            start_date=row.effective_date,
            probation_end_date=(
                row.effective_date + timedelta(days=fields.probation_days)
                if fields.probation_days is not None
                else None
            ),
            owner_user_id=actor.id,
        )
        period = HrEmploymentPeriod(
            employee_id=emp.id,
            started_on=row.effective_date,
            rehire_change_id=row.id,
            onboarding_case_id=onboarding.id,
        )
        self.session.add(period)
        await self.session.flush()
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type="rehire",
                effective_date=row.effective_date,
                previous_snapshot=previous,
                new_snapshot={
                    **self._employee_snapshot(emp),
                    "join_date": row.effective_date.isoformat(),
                    "employment_period_id": str(period.id),
                    "onboarding_case_id": str(onboarding.id),
                },
                reason=row.reason,
                actor_user_id=actor.id,
            )
        )

    async def _check_employment_change_fields(
        self, emp: HrEmployee, fields: EmploymentChangeFields
    ) -> None:
        values = fields.model_dump(exclude_unset=True)
        if all(getattr(emp, name) == value for name, value in values.items()):
            raise AppException("The proposal must change at least one value.", status_code=422)
        if fields.department_id is not None and not await self.session.scalar(
            select(HrDepartment.id).where(
                HrDepartment.id == fields.department_id,
                HrDepartment.is_active.is_(True),
                HrDepartment.deleted_at.is_(None),
            )
        ):
            raise NotFoundException("Active HR department")
        if fields.position_id is not None and not await self.session.scalar(
            select(HrPosition.id).where(
                HrPosition.id == fields.position_id,
                HrPosition.is_active.is_(True),
                HrPosition.deleted_at.is_(None),
            )
        ):
            raise NotFoundException("Active HR position")
        if fields.manager_employee_id is not None:
            manager = await self._require_employee(fields.manager_employee_id)
            if manager.employment_status not in ACTIVE_ASSIGNMENT_EMPLOYMENT:
                raise AppException("Select a current employee as manager.", status_code=422)
            await self._validate_manager_assignment(emp.id, manager.id)

    async def _check_contract_renewal(
        self, emp: HrEmployee, fields: EmploymentChangeFields, effective_date: date, actor: User
    ) -> None:
        if emp.employment_category != "contract":
            raise AppException("Contract renewals require contract employment.", status_code=409)
        current_id = fields.current_contract_document_id
        renewal_id = fields.renewal_contract_document_id
        if current_id is None or renewal_id is None or current_id == renewal_id:
            raise AppException("Select separate current and renewal contracts.", status_code=422)
        docs = list(
            await self.session.scalars(
                select(HrDocument)
                .where(
                    HrDocument.id.in_((current_id, renewal_id)),
                    HrDocument.employee_id == emp.id,
                    HrDocument.candidate_id.is_(None),
                    HrDocument.document_type == "contract",
                    HrDocument.deleted_at.is_(None),
                    HrDocument.status == "active",
                )
                .order_by(HrDocument.id)
                .with_for_update()
            )
        )
        if len(docs) != 2:
            raise NotFoundException("Employee contract")
        for doc in docs:
            self._ensure_hr_doc_access(doc, actor)
        by_id = {doc.id: doc for doc in docs}
        current, renewal = by_id[current_id], by_id[renewal_id]
        renewal_conditions = [
            HrEmploymentChange.employee_id == emp.id,
            HrEmploymentChange.change_type == "contract_renewal",
            HrEmploymentChange.status == "applied",
        ]
        if emp.join_date is not None:
            renewal_conditions.append(HrEmploymentChange.effective_date >= emp.join_date)
        latest = await self.session.scalar(
            select(HrEmploymentChange)
            .where(*renewal_conditions)
            .order_by(HrEmploymentChange.applied_employee_revision.desc())
            .limit(1)
        )
        current_version = fields.current_contract_version
        previous_version: tuple[str, ...] = ("active",)
        if latest is not None:
            if (
                latest.updates["renewal_contract_document_id"] != str(current_id)
                or latest.updates["renewal_contract_version"] != current_version
                or current.expiry_date is None
                or latest.updates["contract_end_date"] != current.expiry_date.isoformat()
            ):
                raise AppException("Start from the last applied contract term.", status_code=409)
            previous_version = ("active", "superseded")

        for doc, number, states in (
            (current, current_version, previous_version),
            (renewal, fields.renewal_contract_version, ("active",)),
        ):
            if not await self.session.scalar(
                select(HrDocumentVersion.id).where(
                    HrDocumentVersion.document_id == doc.id,
                    HrDocumentVersion.version_number == number,
                    HrDocumentVersion.status.in_(states),
                )
            ):
                raise AppException(
                    "A selected contract version is no longer eligible for renewal.",
                    status_code=409,
                )
        if (
            current.expiry_date is None
            or (effective_date - current.expiry_date).days != 1
            or renewal.expiry_date is None
            or renewal.expiry_date != fields.contract_end_date
            or renewal.expiry_date < effective_date
        ):
            raise AppException(
                "Start the renewal the day after current expiry and match the new contract expiry.",
                status_code=422,
            )

    async def get_employment_change(
        self, employee_id: UUID, change_id: UUID, *, lock: bool = False
    ) -> HrEmploymentChange:
        query = select(HrEmploymentChange).where(
            HrEmploymentChange.employee_id == employee_id, HrEmploymentChange.id == change_id
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await self.session.scalar(query)
        if row is None:
            raise NotFoundException("Employment change")
        return row

    async def list_employment_changes(
        self, employee_id: UUID, limit: int, offset: int
    ) -> EmploymentChangeListResponse:
        await self._require_employee(employee_id)
        query = select(HrEmploymentChange).where(HrEmploymentChange.employee_id == employee_id)
        rows = list(
            await self.session.scalars(
                query.order_by(HrEmploymentChange.created_at.desc(), HrEmploymentChange.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        total = await self.session.scalar(
            select(func.count(HrEmploymentChange.id)).where(
                HrEmploymentChange.employee_id == employee_id
            )
        )
        return EmploymentChangeListResponse(
            as_of=business_today(),
            items=[EmploymentChangeResponse.model_validate(row) for row in rows],
            total=total or 0,
        )

    async def list_due_employment_changes(self, limit: int, offset: int) -> DueEmploymentChangeList:
        today = business_today()
        due = (
            select(
                HrEmploymentChange.id,
                HrEmploymentChange.employee_id,
                HrEmployee.employee_code,
                HrEmploymentChange.change_type,
                HrEmploymentChange.effective_date,
                (HrEmploymentChange.employee_revision == HrEmployee.record_revision).label(
                    "revision_matches"
                ),
            )
            .join(HrEmployee, HrEmployee.id == HrEmploymentChange.employee_id)
            .where(
                HrEmploymentChange.status == "approved",
                HrEmploymentChange.effective_date <= today,
                HrEmployee.deleted_at.is_(None),
            )
        )
        total = await self.session.scalar(select(func.count()).select_from(due.subquery()))
        rows = (await self.session.execute(
            due.order_by(HrEmploymentChange.effective_date, HrEmploymentChange.id)
            .limit(limit).offset(offset)
        )).mappings()
        return DueEmploymentChangeList(
            as_of=today, total=total or 0,
            items=[DueEmploymentChange.model_validate(row) for row in rows],
        )

    async def _record_employment_change(self, row: HrEmploymentChange, actor: User) -> None:
        await self.audit.record(
            action=f"hr.employment_change.{row.status}",
            user_id=actor.id,
            entity_type="hr_employment_changes",
            entity_id=row.id,
            new_values={
                "employee_id": str(row.employee_id),
                "change_type": row.change_type,
                "effective_date": row.effective_date.isoformat(),
            },
        )

    async def propose_employment_change(
        self, employee_id: UUID, payload: EmploymentChangeProposal, actor: User
    ) -> HrEmploymentChange:
        ensure_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
        emp = await self._require_employee(employee_id, for_update=True)
        if payload.change_type != "rehire":
            self._check_employment_change_base(
                emp, payload.employee_revision, payload.effective_date
            )
        if payload.effective_date < business_today():
            raise AppException("The proposed date cannot be in the past.", status_code=422)
        if payload.updates.work_location is not None:
            payload.updates.work_location = payload.updates.work_location.strip() or None
        if payload.change_type == "rehire":
            await self._check_rehire(
                emp, payload.updates, payload.employee_revision, payload.effective_date, actor
            )
        elif payload.change_type == "contract_renewal":
            await self._check_contract_renewal(emp, payload.updates, payload.effective_date, actor)
        else:
            await self._check_employment_change_fields(emp, payload.updates)
        row = HrEmploymentChange(
            employee_id=employee_id,
            employee_revision=emp.record_revision,
            change_type=payload.change_type,
            effective_date=payload.effective_date,
            updates=payload.updates.model_dump(mode="json", exclude_unset=True),
            reason=payload.reason.strip(),
            proposed_by=actor.id,
        )
        self.session.add(row)
        await self.session.flush()
        await self._record_employment_change(row, actor)
        await self.session.commit()
        return row

    async def decide_employment_change(
        self, employee_id: UUID, change_id: UUID, payload: EmploymentChangeDecision, actor: User
    ) -> HrEmploymentChange:
        ensure_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
        emp = await self._require_employee(employee_id, for_update=True)
        row = await self.get_employment_change(employee_id, change_id, lock=True)
        if actor.id in {row.proposed_by, emp.user_id}:
            raise PermissionDeniedException("independent employment change review")
        reason = (payload.reason or "").strip() or None
        if payload.decision == "rejected" and reason is None:
            raise AppException("Enter a reason for rejecting the proposal.", status_code=422)
        if row.status != "proposed":
            if (row.status, row.decided_by, row.decision_reason) == (
                payload.decision,
                actor.id,
                reason,
            ):
                return row
            raise AppException("This employment change already has a decision.", status_code=409)
        if payload.decision == "approved":
            if row.change_type == "rehire":
                await self._check_rehire(
                    emp,
                    EmploymentChangeFields.model_validate(row.updates),
                    row.employee_revision,
                    row.effective_date,
                    actor,
                )
            else:
                self._check_employment_change_base(emp, row.employee_revision, row.effective_date)
            if row.change_type == "contract_renewal":
                await self._check_contract_renewal(
                    emp,
                    EmploymentChangeFields.model_validate(row.updates),
                    row.effective_date,
                    actor,
                )
        row.status = payload.decision
        row.decided_by = actor.id
        row.decided_at = utc_now()
        row.decision_reason = reason
        await self._record_employment_change(row, actor)
        await self.session.commit()
        return row

    async def apply_employment_change(
        self, employee_id: UUID, change_id: UUID, actor: User
    ) -> HrEmploymentChange:
        ensure_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE)
        # Match manager edits and leave decisions: payroll guard, reporting-line
        # guard, submitted requests in stable order, then employee/change rows.
        await lock_payroll_periods(self.session)
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_reporting_lines'))")
        )
        pending_leave = list(
            await self.session.scalars(
                select(HrLeaveRequest)
                .where(
                    HrLeaveRequest.employee_id == employee_id,
                    HrLeaveRequest.status == "submitted",
                )
                .order_by(HrLeaveRequest.id)
                .with_for_update()
            )
        )
        emp = await self._require_employee(employee_id, for_update=True)
        previous_manager_id = emp.manager_employee_id
        row = await self.get_employment_change(employee_id, change_id, lock=True)
        if row.status == "applied":
            return row
        if row.status != "approved" or row.effective_date > business_today():
            raise AppException(
                "Apply an approved change on or after its effective date.", status_code=409
            )
        updates = EmploymentChangeFields.model_validate(row.updates)
        if row.change_type == "rehire":
            await self._apply_rehire(emp, row, updates, actor)
        else:
            self._check_employment_change_base(emp, row.employee_revision, row.effective_date)
            contract_history = None
            if row.change_type == "contract_renewal":
                await self._check_contract_renewal(emp, updates, row.effective_date, actor)
                employee_updates = {}
                contract_history = row.updates
            else:
                await self._check_employment_change_fields(emp, updates)
                employee_updates = updates.model_dump(exclude_unset=True)
            await self._stage_employee_update(
                emp,
                EmployeeUpdateRequest(
                    expected_revision=row.employee_revision,
                    reason=row.reason,
                    **employee_updates,
                ),
                actor,
                row.change_type,
                row.effective_date,
                contract_history=contract_history,
            )
        if previous_manager_id != emp.manager_employee_id:
            for leave_request in pending_leave:
                await self._reroute_pending_leave_request(leave_request, emp, actor)
        row.status = "applied"
        row.applied_by = actor.id
        row.applied_at = utc_now()
        row.applied_employee_revision = emp.record_revision
        await self._record_employment_change(row, actor)
        await self.session.commit()
        return row

    async def transition_employee_status(
        self, employee_id: UUID, payload: EmployeeStatusTransitionRequest, actor: User
    ) -> EmployeeDetailResponse:
        emp = await self.session.scalar(
            select(HrEmployee)
            .where(HrEmployee.id == employee_id, HrEmployee.deleted_at.is_(None))
            .with_for_update()
        )
        if emp is None:
            raise NotFoundException("Employee")
        if emp.record_revision != payload.expected_revision:
            raise AppException(
                "Employee record has been modified by another user.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        allowed = {
            "draft": {"onboarding", "active", "on_probation", "archived"},
            "onboarding": {"active", "on_probation"},
            "on_probation": {"active", "suspended"},
            "active": {"suspended"},
            "suspended": {"active"},
            "resigned": {"archived"},
            "terminated": {"archived"},
        }
        if payload.status not in allowed.get(emp.employment_status, set()):
            raise AppException(
                "This employment change is unavailable. Use offboarding for separations.",
                status_code=409,
            )
        if payload.status in {"active", "on_probation"} and await self.session.scalar(
            select(HrOnboardingCase.id)
            .where(
                HrOnboardingCase.employee_id == emp.id,
                HrOnboardingCase.status != "completed",
            )
            .limit(1)
        ):
            raise AppException("Finish onboarding before activating the employee.", status_code=409)
        eff_date = payload.effective_date or business_today()
        if emp.employment_status == "onboarding":
            rehire_case = await self.session.scalar(
                select(HrOnboardingCase)
                .join(
                    HrEmploymentPeriod, HrOnboardingCase.id == HrEmploymentPeriod.onboarding_case_id
                )
                .where(
                    HrEmploymentPeriod.employee_id == emp.id,
                    HrEmploymentPeriod.ended_on.is_(None),
                )
            )
            if rehire_case is not None:
                if not rehire_case.start_date <= eff_date <= business_today():
                    raise AppException(
                        "Choose an activation date within the current employment period.",
                        status_code=422,
                    )
                if payload.status == "active" and rehire_case.probation_end_date is not None:
                    raise AppException(
                        "Start the employee's reviewed probation first.", status_code=409
                    )
        prev = self._employee_snapshot(emp)
        emp.employment_status = payload.status
        if payload.status in {"terminated", "resigned"}:
            emp.termination_date = eff_date
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type=f"status:{payload.status}",
                effective_date=eff_date,
                previous_snapshot=prev,
                new_snapshot=self._employee_snapshot(emp),
                reason=payload.reason,
                actor_user_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.employee.status_changed",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"status": payload.status, "effective_date": eff_date.isoformat()},
        )
        await self._commit_and_refresh(emp)
        return await self._serialize_employee_detail(emp)

    async def record_probation_review(
        self, case_id: UUID, payload: ProbationReviewRequest, actor: User
    ) -> OnboardingCaseResponse:
        if not has_permission(actor, PERMISSION_HR_ONBOARDING_MANAGE):
            raise PermissionDeniedException(PERMISSION_HR_ONBOARDING_MANAGE)
        employee_id = await self.session.scalar(
            select(HrOnboardingCase.employee_id).where(HrOnboardingCase.id == case_id)
        )
        if employee_id is None:
            raise NotFoundException("Onboarding case")
        emp = await self._require_employee(employee_id, for_update=True)
        case = await self.session.scalar(
            select(HrOnboardingCase).where(HrOnboardingCase.id == case_id).with_for_update()
        )
        if case is None:
            raise NotFoundException("Onboarding case")
        if emp.user_id == actor.id:
            raise AppException("Employees cannot review their own probation.", status_code=403)
        if emp.record_revision != payload.expected_employee_revision:
            raise AppException(
                "The employee changed. Reload the case before recording a decision.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )
        if (
            case.status != "completed"
            or not case.probation_end_date
            or emp.employment_status != "on_probation"
        ):
            raise AppException(
                "Select a completed onboarding case for an employee on probation.", status_code=409
            )
        latest_case = await self.session.scalar(
            select(HrOnboardingCase.id)
            .where(HrOnboardingCase.employee_id == emp.id)
            .order_by(HrOnboardingCase.created_at.desc(), HrOnboardingCase.id.desc())
            .limit(1)
        )
        if latest_case != case.id:
            raise AppException(
                "Review probation on the employee's latest onboarding case.", status_code=409
            )
        reason = payload.reason.strip()
        if not reason:
            raise AppException("A probation review reason is required.", status_code=422)
        today = business_today()
        previous = {
            **self._employee_snapshot(emp),
            "probation_end_date": case.probation_end_date.isoformat(),
        }
        if payload.outcome == "extend":
            new_date = payload.new_end_date
            if (
                payload.confirmed_category is not None
                or new_date is None
                or new_date <= max(case.probation_end_date, today)
            ):
                raise AppException(
                    "The new end date must be after the current end date and today.",
                    status_code=422,
                )
            case.probation_end_date = new_date
        else:
            if payload.new_end_date is not None:
                raise AppException("An end date is only needed for an extension.", status_code=422)
            if emp.employment_category == "probation" and payload.confirmed_category is None:
                raise AppException("Select the confirmed employment category.", status_code=422)
            if payload.confirmed_category is not None:
                emp.employment_category = payload.confirmed_category
            emp.employment_status = "active"
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type=f"probation:{payload.outcome}",
                effective_date=today,
                previous_snapshot=previous,
                new_snapshot={
                    **self._employee_snapshot(emp),
                    "probation_end_date": case.probation_end_date.isoformat(),
                },
                reason=reason,
                actor_user_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.probation.reviewed",
            user_id=actor.id,
            entity_type="hr_onboarding_cases",
            entity_id=case.id,
            new_values={
                "outcome": payload.outcome,
                "probation_end_date": case.probation_end_date.isoformat(),
            },
        )
        await self._commit_and_refresh(case)
        return await self._serialize_onboarding_case(case)

    async def list_employment_history(
        self, employee_id: UUID
    ) -> tuple[list[HrEmploymentHistory], int]:
        await self._require_employee(employee_id)
        rows = list(
            await self.session.scalars(
                select(HrEmploymentHistory)
                .where(HrEmploymentHistory.employee_id == employee_id)
                .order_by(HrEmploymentHistory.created_at.desc())
            )
        )
        return rows, len(rows)

    # --- Sensitive Employee Private Data Vault (HR-003) ---

    async def get_employee_private(
        self, employee_id: UUID, actor: User, *, reveal_sensitive: bool = False
    ) -> EmployeeSensitiveResponse:
        employee = await self._require_employee(employee_id)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == employee_id)
        )
        await self.audit.record(
            action="hr.employee_private.viewed",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=employee_id,
            new_values={"reveal_sensitive": reveal_sensitive},
        )
        await self.session.commit()
        if priv is None:
            return EmployeeSensitiveResponse(
                employee_id=employee_id, record_revision=employee.record_revision
            )
        payroll_access = has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        return EmployeeSensitiveResponse(
            employee_id=employee_id,
            record_revision=employee.record_revision,
            national_id_masked=priv.national_id_masked,
            passport_masked=priv.passport_masked,
            date_of_birth=priv.date_of_birth,
            gender=priv.gender,
            marital_status=priv.marital_status,
            nationality=priv.nationality,
            personal_email=priv.personal_email,
            personal_phone=priv.personal_phone,
            residential_address=priv.residential_address,
            emergency_contact_name=priv.emergency_contact_name,
            emergency_contact_phone=priv.emergency_contact_phone,
            emergency_contact_relation=priv.emergency_contact_relation,
            bank_name=priv.bank_name if payroll_access else None,
            bank_branch=priv.bank_branch if payroll_access else None,
            bank_account_masked=priv.bank_account_masked if payroll_access else None,
            tax_id_masked=priv.tax_id_masked if payroll_access else None,
            epf_number_masked=priv.epf_number_masked if payroll_access else None,
            etf_number_masked=priv.etf_number_masked if payroll_access else None,
            national_id_plain=decrypt_hr_value(priv.national_id_encrypted)
            if reveal_sensitive
            else None,
            passport_plain=decrypt_hr_value(priv.passport_encrypted) if reveal_sensitive else None,
            bank_account_plain=decrypt_hr_value(priv.bank_account_encrypted)
            if reveal_sensitive and payroll_access
            else None,
            tax_id_plain=decrypt_hr_value(priv.tax_id_encrypted)
            if reveal_sensitive and payroll_access
            else None,
            epf_number_plain=decrypt_hr_value(priv.epf_number_encrypted)
            if reveal_sensitive and payroll_access
            else None,
            etf_number_plain=decrypt_hr_value(priv.etf_number_encrypted)
            if reveal_sensitive and payroll_access
            else None,
            medical_notes_plain=decrypt_hr_value(priv.medical_notes_encrypted)
            if reveal_sensitive
            else None,
            updated_at=priv.updated_at,
        )

    async def upsert_employee_private(
        self, employee_id: UUID, payload: EmployeePrivateUpdateRequest, actor: User
    ) -> EmployeeSensitiveResponse:
        employee = await self._require_employee(employee_id, for_update=True)
        self._verify_profile_revision(employee, payload.expected_revision)
        updates = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        if not updates:
            raise AppException("Supply at least one profile field.", status_code=422)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == employee_id)
        )
        if priv is None:
            priv = HrEmployeePrivate(employee_id=employee_id)
            self.session.add(priv)

        payroll_fields = {
            "bank_name",
            "bank_branch",
            "bank_account_number",
            "tax_id",
            "epf_number",
            "etf_number",
        }
        if payroll_fields.intersection(updates) and not has_permission(
            actor, PERMISSION_HR_PAYROLL_SENSITIVE
        ):
            raise PermissionDeniedException(PERMISSION_HR_PAYROLL_SENSITIVE)
        encrypted_pairs = {
            "national_id": ("national_id_encrypted", "national_id_masked"),
            "passport_number": ("passport_encrypted", "passport_masked"),
            "bank_account_number": ("bank_account_encrypted", "bank_account_masked"),
            "tax_id": ("tax_id_encrypted", "tax_id_masked"),
            "epf_number": ("epf_number_encrypted", "epf_number_masked"),
            "etf_number": ("etf_number_encrypted", "etf_number_masked"),
        }
        for key, value in updates.items():
            if key in encrypted_pairs:
                enc_col, mask_col = encrypted_pairs[key]
                setattr(priv, enc_col, encrypt_hr_value(value))
                setattr(priv, mask_col, mask_identifier(value))
            elif key == "medical_notes":
                priv.medical_notes_encrypted = encrypt_hr_value(value)
            elif key == "personal_email" and value is not None:
                priv.personal_email = value.lower()
            else:
                setattr(priv, key, value)
        priv.updated_by_id = actor.id
        employee.updated_by_id = actor.id
        employee.record_revision += 1

        await self.audit.record(
            action="hr.employee_private.updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=employee_id,
            new_values={
                "updated_fields": sorted(updates.keys()),
                "record_revision": employee.record_revision,
            },
        )
        await self._commit_and_refresh(priv)
        return await self.get_employee_private(employee_id, actor, reveal_sensitive=False)

    # --- Employee Self-Service (/api/v1/hr/me) ---

    @staticmethod
    def _verify_profile_revision(employee: HrEmployee, expected_revision: int) -> None:
        if employee.record_revision != expected_revision:
            raise AppException(
                "The profile changed after you opened it. Reload the latest details before saving.",
                status_code=409,
                error_code="REVISION_CONFLICT",
            )

    async def get_self_profile(self, actor: User) -> EmployeeSelfResponse:
        emp = await self._employee_for_user(actor)
        detail = await self._serialize_employee_detail(emp)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == emp.id)
        )
        return EmployeeSelfResponse(
            employee=detail,
            personal_email=priv.personal_email if priv else None,
            personal_phone=priv.personal_phone if priv else None,
            residential_address=priv.residential_address if priv else None,
            emergency_contact_name=priv.emergency_contact_name if priv else None,
            emergency_contact_phone=priv.emergency_contact_phone if priv else None,
            emergency_contact_relation=priv.emergency_contact_relation if priv else None,
            bank_name=priv.bank_name if priv else None,
            bank_account_masked=priv.bank_account_masked if priv else None,
            tax_id_masked=priv.tax_id_masked if priv else None,
            epf_number_masked=priv.epf_number_masked if priv else None,
            etf_number_masked=priv.etf_number_masked if priv else None,
        )

    async def update_self_profile(
        self, payload: EmployeeSelfUpdateRequest, actor: User
    ) -> EmployeeSelfResponse:
        emp = await self._employee_for_user(actor, for_update=True)
        self._verify_profile_revision(emp, payload.expected_revision)
        updates = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        if not updates:
            raise AppException("Supply at least one profile field.", status_code=422)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == emp.id)
        )
        if priv is None:
            priv = HrEmployeePrivate(employee_id=emp.id)
            self.session.add(priv)
        if "preferred_name" in updates:
            emp.preferred_name = updates["preferred_name"]
        if "work_phone" in updates:
            emp.work_phone = updates["work_phone"]
        for field in (
            "personal_email",
            "personal_phone",
            "residential_address",
            "emergency_contact_name",
            "emergency_contact_phone",
            "emergency_contact_relation",
        ):
            if field in updates:
                val = updates[field]
                setattr(priv, field, val.lower() if field == "personal_email" and val else val)
        priv.updated_by_id = actor.id
        emp.updated_by_id = actor.id
        emp.record_revision += 1
        await self.audit.record(
            action="hr.self_profile.updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"fields": sorted(updates.keys()), "record_revision": emp.record_revision},
        )
        await self._commit_and_refresh(emp, priv)
        return await self.get_self_profile(actor)

    # --- Portal Account Link & Access Requests (HR-005) ---

    async def link_employee_account(
        self, employee_id: UUID, payload: EmployeeLinkAccountRequest, actor: User
    ) -> EmployeeDetailResponse:
        emp = await self._require_employee(employee_id, for_update=True)
        target_user = await self.session.scalar(
            select(User).where(User.id == payload.user_id, User.deleted_at.is_(None))
        )
        if target_user is None:
            raise NotFoundException("User")
        await self._verify_account_link(emp, target_user)
        emp.user_id = target_user.id
        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type="portal_account_linked",
                effective_date=utc_now().date(),
                previous_snapshot=None,
                new_snapshot={"user_id": str(target_user.id)},
                reason="Linked employee to portal user account",
                actor_user_id=actor.id,
            )
        )
        await self.audit.record(
            action="hr.employee.account_linked",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"user_id": str(target_user.id)},
        )
        await self._commit_and_refresh(emp)
        return await self._serialize_employee_detail(emp)

    async def _verify_account_link(self, emp: HrEmployee, target_user: User) -> None:
        if (
            not target_user.is_active
            or target_user.role not in BUSINESS_ROLES
            or not emp.work_email
            or emp.work_email.casefold() != target_user.email.casefold()
        ):
            raise AppException(
                "The employee's verified work email must match an active portal account.",
                status_code=409,
                error_code="HR_ACCOUNT_IDENTITY_MISMATCH",
            )
        if emp.user_id and emp.user_id != target_user.id:
            raise AppException(
                "The employee already has a portal account link.",
                status_code=409,
                error_code="EMPLOYEE_ALREADY_LINKED",
            )
        existing_emp = await self.session.scalar(
            select(HrEmployee).where(
                HrEmployee.user_id == target_user.id,
                HrEmployee.id != emp.id,
                HrEmployee.deleted_at.is_(None),
            )
        )
        if existing_emp is not None:
            raise AppException(
                "This user account is already linked to another employee.",
                status_code=409,
                error_code="USER_ALREADY_LINKED",
            )

    async def _check_reactivation_period(self, emp: HrEmployee, req: HrAccessRequest) -> None:
        if emp.employment_status in {"resigned", "terminated", "archived", "notice_period"}:
            raise AppException("Complete the reviewed rehire before reactivation.", status_code=409)
        rehire_applied_at = await self.session.scalar(
            select(HrEmploymentChange.applied_at)
            .join(HrEmploymentPeriod, HrEmploymentPeriod.rehire_change_id == HrEmploymentChange.id)
            .where(HrEmploymentPeriod.employee_id == emp.id, HrEmploymentPeriod.ended_on.is_(None))
        )
        if rehire_applied_at is not None and req.created_at <= rehire_applied_at:
            raise AppException("Create a fresh access request after rehire.", status_code=409)

    async def create_access_request(
        self, payload: AccessRequestCreateRequest, actor: User
    ) -> HrAccessRequest:
        await self._require_employee(payload.employee_id)
        normalized_role = validate_role(payload.requested_role) if payload.requested_role else None
        if normalized_role is not None and normalized_role not in BUSINESS_ROLES:
            raise PermissionDeniedException("request a technical role through HR")
        req = HrAccessRequest(
            employee_id=payload.employee_id,
            request_type=payload.request_type,
            requested_role=normalized_role,
            requested_email=payload.requested_email.lower() if payload.requested_email else None,
            portal_access_required=payload.portal_access_required,
            business_title_source=payload.business_title_source,
            status="submitted" if payload.submit_immediately else "draft",
            justification=payload.justification,
            requested_by_id=actor.id,
        )
        self.session.add(req)
        await self.session.flush()
        await self.audit.record(
            action="hr.access_request.created",
            user_id=actor.id,
            entity_type="hr_access_requests",
            entity_id=req.id,
            new_values={"request_type": req.request_type, "status": req.status},
        )
        await self._commit_and_refresh(req)
        return req

    async def list_access_requests(
        self, *, status: str | None = None
    ) -> tuple[list[HrAccessRequest], int]:
        stmt = select(HrAccessRequest)
        if status:
            stmt = stmt.where(HrAccessRequest.status == status)
        rows = list(await self.session.scalars(stmt.order_by(HrAccessRequest.created_at.desc())))
        return rows, len(rows)

    async def decide_access_request(
        self, request_id: UUID, payload: AccessRequestDecisionRequest, actor: User
    ) -> HrAccessRequest:
        req = await self.session.scalar(
            select(HrAccessRequest).where(HrAccessRequest.id == request_id).with_for_update()
        )
        if req is None:
            raise NotFoundException("Access request")
        emp = await self._require_employee(req.employee_id, for_update=True)
        if req.status in {"admin_actioned", "rejected", "cancelled"}:
            raise AppException(
                "The access request is closed.", status_code=409, error_code="INVALID_STATE"
            )

        if payload.action in {"submit", "cancel"} and req.requested_by_id != actor.id:
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
        if payload.action == "reject" and not any(
            has_permission(actor, perm)
            for perm in (PERMISSION_HR_EMPLOYEES_SENSITIVE, PERMISSION_USERS_MANAGE)
        ):
            raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)

        if payload.action == "submit":
            if req.status != "draft":
                raise AppException(
                    "Only draft requests can be submitted.",
                    status_code=409,
                    error_code="INVALID_STATE",
                )
            req.status = "submitted"
        elif payload.action == "hr_approve":
            if not has_permission(actor, PERMISSION_HR_EMPLOYEES_SENSITIVE):
                raise PermissionDeniedException(PERMISSION_HR_EMPLOYEES_SENSITIVE)
            if req.status != "submitted":
                raise AppException(
                    "Only submitted requests can be HR-approved.",
                    status_code=409,
                    error_code="INVALID_STATE",
                )
            if emp.user_id == actor.id or req.requested_by_id == actor.id:
                raise AppException(
                    "Dual-control required: requester or subject cannot self-approve.",
                    status_code=403,
                    error_code="SELF_APPROVAL_BLOCKED",
                )
            req.status = "hr_approved"
            req.hr_approved_by_id = actor.id
            req.hr_approved_at = utc_now()
            req.hr_decision_notes = payload.notes
        elif payload.action == "admin_action":
            if not has_permission(actor, PERMISSION_USERS_MANAGE):
                raise PermissionDeniedException(PERMISSION_USERS_MANAGE)
            if actor.id in {req.requested_by_id, req.hr_approved_by_id, emp.user_id}:
                raise AppException(
                    "An independent director must fulfill the request.",
                    status_code=403,
                    error_code="SELF_APPROVAL_BLOCKED",
                )
            if req.status != "hr_approved":
                raise AppException(
                    "Only HR-approved access requests can be actioned by IT Admin.",
                    status_code=409,
                    error_code="INVALID_STATE",
                )
            return await self._execute_admin_access_action(req, emp, payload, actor)
        elif payload.action == "reject":
            req.status = "rejected"
            if has_permission(actor, PERMISSION_USERS_MANAGE):
                req.admin_decision_notes = payload.notes
            else:
                req.hr_decision_notes = payload.notes
        elif payload.action == "cancel":
            if req.status == "admin_actioned":
                raise AppException(
                    "Completed access requests cannot be cancelled.",
                    status_code=409,
                    error_code="INVALID_STATE",
                )
            req.status = "cancelled"

        await self.audit.record(
            action=f"hr.access_request.{payload.action}",
            user_id=actor.id,
            entity_type="hr_access_requests",
            entity_id=req.id,
        )
        await self._commit_and_refresh(req)
        return req

    async def _execute_admin_access_action(
        self,
        req: HrAccessRequest,
        emp: HrEmployee,
        payload: AccessRequestDecisionRequest,
        actor: User,
    ) -> HrAccessRequest:
        users_svc = UserService(self.session)
        linked_user: User | None = None

        if payload.link_existing_user_id and req.request_type != "link_existing":
            raise AppException(
                "This request cannot link an existing account.",
                status_code=422,
                error_code="INVALID_ACCESS_ACTION",
            )
        if req.request_type == "provision":
            email = req.requested_email or emp.work_email
            if (
                not emp.work_email
                or email != emp.work_email
                or not emp.work_phone
                or emp.employee_code.upper().startswith("DRAFT-")
                or not req.requested_role
                or not payload.temporary_password
                or emp.user_id
            ):
                raise AppException(
                    "Provisioning requires a matching work email, work phone, role, "
                    "temporary password, and an unlinked employee.",
                    status_code=422,
                    error_code="PROVISION_PARAMS_REQUIRED",
                )
            linked_user = await users_svc.create_user(
                UserCreateRequest(
                    email=email,
                    full_name=emp.full_name,
                    role=req.requested_role,
                    employee_code=emp.employee_code,
                    phone=emp.work_phone,
                    designation=req.business_title_source,
                    temporary_password=payload.temporary_password,
                ),
                actor,
                commit=False,
            )
        elif req.request_type == "link_existing":
            target_uid = payload.link_existing_user_id or req.linked_user_id
            if not target_uid:
                raise AppException(
                    "Target user_id is required to link an existing portal user.",
                    status_code=422,
                    error_code="TARGET_USER_REQUIRED",
                )
            linked_user = await users_svc.get_user(target_uid)
            await self._verify_account_link(emp, linked_user)
        elif req.request_type in {"role_change", "deactivate", "reactivate"}:
            if req.request_type == "reactivate":
                await self._check_reactivation_period(emp, req)
            target_uid = emp.user_id or req.linked_user_id
            if not target_uid:
                raise AppException(
                    "Employee has no linked user account for this action.",
                    status_code=409,
                    error_code="NO_LINKED_USER",
                )
            if req.request_type == "role_change" and not req.requested_role:
                raise AppException(
                    "A role change requires a canonical role.",
                    status_code=422,
                    error_code="PROVISION_PARAMS_REQUIRED",
                )
            existing_user = await users_svc.get_user(target_uid)
            linked_user = await users_svc.update_user(
                existing_user.id,
                UserUpdateRequest(
                    expected_updated_at=existing_user.updated_at,
                    role=req.requested_role if req.request_type == "role_change" else None,
                    is_active=(
                        False
                        if req.request_type == "deactivate"
                        else (True if req.request_type == "reactivate" else None)
                    ),
                ),
                actor,
                commit=False,
            )

        if linked_user is not None:
            if emp.user_id != linked_user.id:
                emp.user_id = linked_user.id
                emp.record_revision += 1
                emp.updated_by_id = actor.id
            req.linked_user_id = linked_user.id
        req.status = "admin_actioned"
        req.admin_actioned_by_id = actor.id
        req.admin_actioned_at = utc_now()
        req.admin_decision_notes = payload.notes
        await self.audit.record(
            action="hr.access_request.admin_actioned",
            user_id=actor.id,
            entity_type="hr_access_requests",
            entity_id=req.id,
            new_values={
                "linked_user_id": str(linked_user.id) if linked_user else None,
                "request_type": req.request_type,
            },
        )
        await self._commit_and_refresh(req)
        return req
