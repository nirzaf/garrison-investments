from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrAccessRequest,
    HrDepartment,
    HrEmployee,
    HrEmployeePrivate,
    HrEmploymentHistory,
    HrOnboardingCase,
    HrPosition,
)
from app.models.user import User
from app.schemas.hr import (
    AccessRequestCreateRequest,
    AccessRequestDecisionRequest,
    DepartmentCreateRequest,
    DepartmentUpdateRequest,
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
    OrgChartNode,
    OrgChartResponse,
    PositionCreateRequest,
    PositionUpdateRequest,
)
from app.schemas.users import UserCreateRequest, UserUpdateRequest
from app.services.hr_crypto import decrypt_hr_value, encrypt_hr_value, mask_identifier
from app.services.hr_manager_review import eligible_reviewer
from app.services.hr_workforce_service import HrWorkforceService
from app.services.user_service import UserService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_EMPLOYEES_SENSITIVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    PERMISSION_HR_POLICY_MANAGE,
    PERMISSION_USERS_MANAGE,
    has_permission,
    validate_role,
)
from app.utils.security import utc_now


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
            select(HrPosition).where(HrPosition.id == position_id, HrPosition.deleted_at.is_(None))
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
        if "manager_employee_id" in payload.model_fields_set:
            await self.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_reporting_lines'))")
            )
        emp = await self._require_employee(employee_id, for_update=True)
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
        for field, value in updates.items():
            if field == "work_email" and value is not None:
                value = value.lower()
            setattr(emp, field, value)
        if ("first_name" in updates or "last_name" in updates) and "full_name" not in updates:
            emp.full_name = f"{emp.first_name.strip()} {emp.last_name.strip()}"

        emp.record_revision += 1
        emp.updated_by_id = actor.id
        self.session.add(
            HrEmploymentHistory(
                employee_id=emp.id,
                change_type="updated",
                effective_date=utc_now().date(),
                previous_snapshot=prev,
                new_snapshot=self._employee_snapshot(emp),
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
        prev = self._employee_snapshot(emp)
        eff_date = payload.effective_date or utc_now().date()
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
        await self._require_employee(employee_id)
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
            return EmployeeSensitiveResponse(employee_id=employee_id)
        payroll_access = has_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)
        return EmployeeSensitiveResponse(
            employee_id=employee_id,
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
        await self._require_employee(employee_id)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == employee_id)
        )
        if priv is None:
            priv = HrEmployeePrivate(employee_id=employee_id)
            self.session.add(priv)

        updates = payload.model_dump(exclude_unset=True)
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

        await self.audit.record(
            action="hr.employee_private.updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=employee_id,
            new_values={"updated_fields": sorted(updates.keys())},
        )
        await self._commit_and_refresh(priv)
        return await self.get_employee_private(employee_id, actor, reveal_sensitive=False)

    # --- Employee Self-Service (/api/v1/hr/me) ---

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
        emp = await self._employee_for_user(actor)
        priv = await self.session.scalar(
            select(HrEmployeePrivate).where(HrEmployeePrivate.employee_id == emp.id)
        )
        if priv is None:
            priv = HrEmployeePrivate(employee_id=emp.id)
            self.session.add(priv)
        updates = payload.model_dump(exclude_unset=True)
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
        await self.audit.record(
            action="hr.self_profile.updated",
            user_id=actor.id,
            entity_type="hr_employees",
            entity_id=emp.id,
            new_values={"fields": sorted(updates.keys())},
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

    async def create_access_request(
        self, payload: AccessRequestCreateRequest, actor: User
    ) -> HrAccessRequest:
        await self._require_employee(payload.employee_id)
        normalized_role = validate_role(payload.requested_role) if payload.requested_role else None
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
