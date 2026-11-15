"""Service-level regression tests for canonical ten-role transitions and policy guards."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_report import DailyReport
from app.models.finance import Invoice
from app.models.project import Project
from app.models.supervisor_update import SupervisorUpdate
from app.models.user import User
from app.schemas.finance import InvoiceCreateRequest, InvoiceUpdateRequest, PaymentCreateRequest
from app.schemas.projects import ProjectOption
from app.schemas.supervisor_updates import SupervisorUpdateCreateRequest
from app.schemas.users import AdminPasswordResetRequest, UserUpdateRequest
from app.services.finance_service import FinanceService
from app.services.project_service import ProjectService
from app.services.report_service import ReportService
from app.services.reporting_service import ReportingService
from app.services.user_service import UserService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    VALID_ROLES,
    can_assign_user_role,
    has_permission,
)

RETIRED_ROLES = (
    "admin",
    "general_manager",
    "operation_manager",
    "project_manager",
    "civil_engineer",
    "civil_supervisor",
    "store_keeper",
    "accounts",
)
HRM_ALLOWED_TARGETS = {
    "group_project_manager",
    "mep_project_manager",
    "quantity_surveyor",
    "senior_site_supervisor",
    "site_supervisor",
    "hr_executive",
    "administrative_executive",
}
PROTECTED_TARGETS = {"managing_director", "operations_director", "hr_manager"}


class _StubSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _StubUserRepo:
    def __init__(self, users: dict[UUID, User], *, other_usable_director: bool = True) -> None:
        self._users = users
        self._other_usable_director = other_usable_director

    async def lock_access_management(self) -> None:
        return None

    async def lock_users(
        self, *user_ids: UUID, include_active_directors: bool = False
    ) -> dict[UUID, User]:
        del include_active_directors
        return {uid: self._users[uid] for uid in user_ids if uid in self._users}

    async def has_other_usable_director(self, excluded_user_id: UUID) -> bool:
        del excluded_user_id
        return self._other_usable_director


class _StubAuthRepo:
    def __init__(self) -> None:
        self.revoked_user_ids: list[UUID] = []

    async def revoke_user_authentication(self, user_id: UUID) -> None:
        self.revoked_user_ids.append(user_id)


class _StubAudit:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


def _user(
    role: str,
    *,
    user_id: UUID | None = None,
    is_active: bool = True,
    updated_at: datetime | None = None,
    access_revision: int = 1,
) -> User:
    return User(
        id=user_id or uuid4(),
        email=f"{role}-{uuid4().hex[:6]}@example.com",
        full_name=f"User {role}",
        role=role,
        employee_code=f"EMP-{uuid4().hex[:6]}",
        phone="+97450000000",
        designation=role.replace("_", " ").title(),
        password_hash="hashed-password",
        is_active=is_active,
        access_revision=access_revision,
        must_change_password=False,
        updated_at=updated_at or datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
    )


def _user_service(
    users: list[User], *, other_usable_director: bool = True
) -> tuple[UserService, _StubAuthRepo, _StubSession]:
    session = _StubSession()
    service = UserService(cast(AsyncSession, session))
    by_id = {u.id: u for u in users}
    auth_repo = _StubAuthRepo()
    service.users = cast(Any, _StubUserRepo(by_id, other_usable_director=other_usable_director))
    service.auth = cast(Any, auth_repo)
    service.audit = cast(Any, _StubAudit())
    return service, auth_repo, session


def test_role_assignment_ceilings_match_policy() -> None:
    assert set(VALID_ROLES) == HRM_ALLOWED_TARGETS | PROTECTED_TARGETS
    for director_role in COMPANY_RESOURCE_ROLES:
        for target_role in VALID_ROLES:
            assert can_assign_user_role(director_role, target_role) is True
        for retired_role in RETIRED_ROLES:
            assert can_assign_user_role(director_role, retired_role) is False

    for target_role in HRM_ALLOWED_TARGETS:
        assert can_assign_user_role("hr_manager", target_role) is True
    for protected_role in PROTECTED_TARGETS:
        assert can_assign_user_role("hr_manager", protected_role) is False
    for retired_role in RETIRED_ROLES:
        assert can_assign_user_role("hr_manager", retired_role) is False

    for non_manager in VALID_ROLES - {"managing_director", "operations_director", "hr_manager"}:
        for target_role in VALID_ROLES:
            assert can_assign_user_role(non_manager, target_role) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("protected_role", sorted(PROTECTED_TARGETS))
async def test_hrm_cannot_mutate_or_assign_protected_roles(protected_role: str) -> None:
    snapshot = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    hrm = _user("hr_manager", updated_at=snapshot)
    protected_target = _user(protected_role, updated_at=snapshot)
    regular_target = _user("quantity_surveyor", updated_at=snapshot)
    service, auth_repo, session = _user_service([hrm, protected_target, regular_target])

    with pytest.raises(AppException) as mutate_exc:
        await service.update_user(
            protected_target.id,
            UserUpdateRequest(role="quantity_surveyor", expected_updated_at=snapshot),
            hrm,
        )
    assert mutate_exc.value.status_code == 403
    assert mutate_exc.value.error_code == "PERMISSION_DENIED"
    assert protected_target.role == protected_role

    with pytest.raises(AppException) as promote_exc:
        await service.update_user(
            regular_target.id,
            UserUpdateRequest(role=protected_role, expected_updated_at=snapshot),
            hrm,
        )
    assert promote_exc.value.status_code == 403
    assert promote_exc.value.error_code == "PERMISSION_DENIED"
    assert regular_target.role == "quantity_surveyor"
    assert auth_repo.revoked_user_ids == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_hrm_can_assign_allowed_targets_and_directors_can_manage_all_roles() -> None:
    snapshot = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    hrm = _user("hr_manager", updated_at=snapshot)
    director = _user("managing_director", updated_at=snapshot)
    worker = _user("quantity_surveyor", updated_at=snapshot, access_revision=2)
    hrm_target = _user("hr_executive", updated_at=snapshot, access_revision=3)
    service, auth_repo, session = _user_service([hrm, director, worker, hrm_target])

    updated = await service.update_user(
        worker.id,
        UserUpdateRequest(role="site_supervisor", expected_updated_at=snapshot),
        hrm,
    )
    assert updated.role == "site_supervisor"
    assert updated.access_revision == 3
    assert worker.id in auth_repo.revoked_user_ids

    promoted = await service.update_user(
        hrm_target.id,
        UserUpdateRequest(role="hr_manager", expected_updated_at=snapshot),
        director,
    )
    assert promoted.role == "hr_manager"
    assert promoted.access_revision == 4
    assert hrm_target.id in auth_repo.revoked_user_ids
    assert session.commits == 2


@pytest.mark.asyncio
async def test_user_update_rejects_self_modification_and_last_usable_director_removal() -> None:
    snapshot = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    director = _user("managing_director", updated_at=snapshot)
    other_director = _user("operations_director", updated_at=snapshot)

    service_with_backup, auth_repo, session = _user_service(
        [director, other_director], other_usable_director=True
    )
    with pytest.raises(AppException) as self_role_exc:
        await service_with_backup.update_user(
            director.id,
            UserUpdateRequest(role="operations_director", expected_updated_at=snapshot),
            director,
        )
    assert self_role_exc.value.status_code == 409
    assert self_role_exc.value.error_code == "SELF_ROLE_CHANGE_BLOCKED"

    with pytest.raises(AppException) as self_deactivate_exc:
        await service_with_backup.deactivate_user(
            director.id, director, expected_updated_at=snapshot
        )
    assert self_deactivate_exc.value.status_code == 409
    assert self_deactivate_exc.value.error_code == "SELF_DEACTIVATION_BLOCKED"
    assert auth_repo.revoked_user_ids == []
    assert session.commits == 0

    sole_service, sole_auth, sole_session = _user_service(
        [director, other_director], other_usable_director=False
    )
    with pytest.raises(AppException) as demote_exc:
        await sole_service.update_user(
            other_director.id,
            UserUpdateRequest(role="hr_manager", expected_updated_at=snapshot),
            director,
        )
    assert demote_exc.value.status_code == 409
    assert demote_exc.value.error_code == "LAST_ACCESS_MANAGER_REQUIRED"

    with pytest.raises(AppException) as deactivate_exc:
        await sole_service.deactivate_user(
            other_director.id, director, expected_updated_at=snapshot
        )
    assert deactivate_exc.value.status_code == 409
    assert deactivate_exc.value.error_code == "LAST_ACCESS_MANAGER_REQUIRED"
    assert other_director.role == "operations_director"
    assert other_director.is_active is True
    assert sole_auth.revoked_user_ids == []
    assert sole_session.commits == 0


@pytest.mark.asyncio
async def test_user_access_mutations_require_expected_updated_at_precondition() -> None:
    snapshot = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    stale_snapshot = datetime(2026, 11, 14, 11, 0, tzinfo=UTC)
    director = _user("managing_director", updated_at=snapshot)
    target = _user("quantity_surveyor", updated_at=snapshot)
    service, auth_repo, session = _user_service([director, target])

    with pytest.raises(AppException) as missing_role_precond:
        await service.update_user(target.id, UserUpdateRequest(role="site_supervisor"), director)
    assert missing_role_precond.value.status_code == 422
    assert missing_role_precond.value.error_code == "USER_PRECONDITION_REQUIRED"

    with pytest.raises(AppException) as missing_active_precond:
        await service.update_user(target.id, UserUpdateRequest(is_active=False), director)
    assert missing_active_precond.value.status_code == 422
    assert missing_active_precond.value.error_code == "USER_PRECONDITION_REQUIRED"

    with pytest.raises(AppException) as missing_reset_precond:
        await service.admin_reset_password(
            target.id, AdminPasswordResetRequest(new_password="ValidPassword1!"), director
        )
    assert missing_reset_precond.value.status_code == 422
    assert missing_reset_precond.value.error_code == "USER_PRECONDITION_REQUIRED"

    with pytest.raises(AppException) as stale_exc:
        await service.update_user(
            target.id,
            UserUpdateRequest(role="site_supervisor", expected_updated_at=stale_snapshot),
            director,
        )
    assert stale_exc.value.status_code == 409
    assert stale_exc.value.error_code == "USER_STATE_CONFLICT"
    assert target.role == "quantity_surveyor"
    assert auth_repo.revoked_user_ids == []
    assert session.commits == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_role", RETIRED_ROLES)
async def test_retired_roles_are_rejected_by_user_updates(retired_role: str) -> None:
    snapshot = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    director = _user("managing_director", updated_at=snapshot)
    target = _user("quantity_surveyor", updated_at=snapshot)
    service, _, _ = _user_service([director, target])

    with pytest.raises(AppException) as exc_info:
        await service.update_user(
            target.id,
            UserUpdateRequest(role=retired_role, expected_updated_at=snapshot),
            director,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "INVALID_ROLE"


@pytest.mark.asyncio
async def test_official_report_own_work_recovery_and_self_approval_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ReportService(cast(AsyncSession, _StubSession()))
    project_id = uuid4()
    qs = _user("quantity_surveyor")
    other_author = _user("quantity_surveyor")

    assert has_permission(qs, PERMISSION_REPORTS_SUBMIT) is True
    assert has_permission(qs, PERMISSION_REPORTS_VIEW) is False

    async def is_member(pid: UUID, actor: User) -> SimpleNamespace:
        del pid, actor
        return SimpleNamespace(id=project_id)

    monkeypatch.setattr(service, "_ensure_project_member", is_member)

    own_report = DailyReport(id=uuid4(), project_id=project_id, engineer_id=qs.id, status="draft")
    await service._ensure_report_access(own_report, qs)

    foreign_report = DailyReport(
        id=uuid4(), project_id=project_id, engineer_id=other_author.id, status="draft"
    )
    with pytest.raises(NotFoundException):
        await service._ensure_report_access(foreign_report, qs)

    for director_role in ("managing_director", "operations_director"):
        director = _user(director_role)
        submitted_own = DailyReport(
            id=uuid4(), project_id=project_id, engineer_id=director.id, status="submitted"
        )

        async def get_own(_rid: UUID, *, for_update: bool = False, report=submitted_own) -> Any:
            del _rid, for_update
            return report

        monkeypatch.setattr(service, "_get_required", get_own)
        with pytest.raises(AppException) as self_approve_exc:
            await service.approve_report(submitted_own.id, director, target_covered=True)
        assert self_approve_exc.value.status_code == 403
        assert self_approve_exc.value.error_code == "REPORT_SELF_APPROVAL_FORBIDDEN"

    for role in ("hr_manager", "managing_director"):
        actor = _user(role)
        with pytest.raises(AppException) as override_exc:
            await service.override_report(
                own_report.id,
                actor,
                decision="approved",
                reason="Retired bypass check",
                target_covered=True,
            )
        assert override_exc.value.status_code == 403
        assert override_exc.value.error_code == "DAILY_REPORT_OVERRIDE_FORBIDDEN"


@pytest.mark.asyncio
async def test_supervisor_updates_require_current_supervisor_role_and_ownership() -> None:
    session = _StubSession()
    service = ReportingService(cast(AsyncSession, session))
    project_id = uuid4()
    today = date.today()
    sss = _user("senior_site_supervisor")
    ss = _user("site_supervisor")
    demoted = _user("hr_executive")

    updates_store: dict[UUID, SupervisorUpdate] = {}

    class _ProjRepo:
        async def get_by_id(self, pid: UUID) -> SimpleNamespace | None:
            return SimpleNamespace(id=pid) if pid == project_id else None

        async def list_members(self, pid: UUID) -> list[SimpleNamespace]:
            del pid
            return [
                SimpleNamespace(user_id=sss.id),
                SimpleNamespace(user_id=ss.id),
                SimpleNamespace(user_id=demoted.id),
            ]

    class _UpdateRepo:
        async def add(self, upd: SupervisorUpdate) -> SupervisorUpdate:
            if upd.id is None:
                upd.id = uuid4()
            updates_store[upd.id] = upd
            return upd

        async def get_by_id(
            self, update_id: UUID, *, for_update: bool = False
        ) -> SupervisorUpdate | None:
            del for_update
            return updates_store.get(update_id)

    service.projects = cast(Any, _ProjRepo())
    service.updates = cast(Any, _UpdateRepo())
    service.audit = cast(Any, _StubAudit())

    payload = SupervisorUpdateCreateRequest(
        project_id=project_id,
        update_date=today,
        day_type="weekday",
        work_location="Block A",
        attendance_count=5,
        overtime_hours=Decimal("1.0"),
        progress_notes="Installed formwork.",
        required_notes="Concrete pour next.",
        attachment_refs=[],
    )

    for supervisor in (sss, ss):
        created = await service.create_supervisor_update(payload, supervisor)
        assert created.status == "draft"
        submitted = await service.submit_supervisor_update(created.id, supervisor)
        assert submitted.status == "submitted"

    demoted_draft = SupervisorUpdate(
        id=uuid4(),
        project_id=project_id,
        supervisor_id=demoted.id,
        update_date=today,
        day_type="weekday",
        work_location="Block B",
        attendance_count=2,
        overtime_hours=Decimal("0"),
        progress_notes="Draft before role change.",
        required_notes="None",
        attachment_refs=[],
        status="draft",
    )
    updates_store[demoted_draft.id] = demoted_draft

    with pytest.raises(AppException) as create_denied:
        await service.create_supervisor_update(payload, demoted)
    assert create_denied.value.status_code == 403

    with pytest.raises(AppException) as edit_denied:
        await service.update_supervisor_update(demoted_draft.id, payload, demoted)
    assert edit_denied.value.status_code == 403

    with pytest.raises(AppException) as submit_denied:
        await service.submit_supervisor_update(demoted_draft.id, demoted)
    assert submit_denied.value.status_code == 403

    with pytest.raises(NotFoundException):
        await service.submit_supervisor_update(demoted_draft.id, ss)


@pytest.mark.asyncio
async def test_narrow_project_options_do_not_require_projects_read_or_leak_budgets() -> None:
    service = ProjectService(cast(AsyncSession, _StubSession()))
    observed_unrestricted: list[bool] = []
    sample_project = Project(
        id=uuid4(),
        name="Lusail Tower",
        code="LT-01",
        location="Doha",
        description="Desc",
        scope_of_work="Scope",
        status="active",
        budget_amount=Decimal("950000.00"),
        start_date=date(2026, 1, 1),
        target_end_date=date(2026, 12, 31),
        progress_percentage=Decimal("10.00"),
        revision=1,
    )

    class _ProjRepo:
        async def list_projects(
            self, *, unrestricted: bool, **kwargs: Any
        ) -> tuple[list[Project], int]:
            del kwargs
            observed_unrestricted.append(unrestricted)
            return [sample_project], 1

    service.projects = cast(Any, _ProjRepo())

    qs = _user("quantity_surveyor")
    ae = _user("administrative_executive")
    hrm = _user("hr_manager")

    qs_options, total = await service.list_report_project_options(
        qs, search=None, limit=50, offset=0
    )
    assert total == 1
    assert len(qs_options) == 1
    assert isinstance(qs_options[0], ProjectOption)
    assert set(qs_options[0].model_dump()) == {"id", "name", "code"}
    assert observed_unrestricted[-1] is False

    with pytest.raises(AppException) as ae_report_exc:
        await service.list_report_project_options(ae, search=None, limit=50, offset=0)
    assert ae_report_exc.value.status_code == 403

    for scoped_doc_reader in (qs, hrm, ae):
        doc_options, doc_total = await service.list_document_project_options(
            scoped_doc_reader, search=None, limit=50, offset=0
        )
        assert doc_total == 1
        assert set(doc_options[0].model_dump()) == {"id", "name", "code"}
        assert observed_unrestricted[-1] is False


@pytest.mark.asyncio
async def test_finance_is_read_only_for_directors_and_denied_for_other_roles() -> None:
    service = FinanceService(cast(AsyncSession, _StubSession()))

    for role in VALID_ROLES:
        actor = _user(role)
        if role in COMPANY_RESOURCE_ROLES:
            service.ensure_finance_access(actor)
        else:
            with pytest.raises(AppException) as exc_info:
                service.ensure_finance_access(actor)
            assert exc_info.value.status_code == 403
            assert exc_info.value.error_code == "FINANCE_FORBIDDEN"

    sample_invoice = Invoice(
        id=uuid4(),
        invoice_number="INV-001",
        project_id=uuid4(),
        invoice_date=date(2026, 11, 1),
        due_date=date(2026, 11, 30),
        amount=Decimal("100.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("100.00"),
        status="submitted",
        payment_status="unpaid",
    )

    for role in VALID_ROLES:
        actor = _user(role)
        assert service._invoice_actions(
            sample_invoice, actor, has_payments=False, own_approval=False
        ) == []

        with pytest.raises(AppException) as create_exc:
            await service.create_invoice(
                InvoiceCreateRequest(
                    invoice_number="INV-002",
                    project_id=uuid4(),
                    invoice_date=date(2026, 11, 1),
                    due_date=date(2026, 11, 30),
                    amount=Decimal("500.00"),
                ),
                actor,
            )
        assert create_exc.value.status_code == 403
        assert create_exc.value.error_code == "FINANCE_WRITE_FORBIDDEN"

        with pytest.raises(AppException) as update_exc:
            await service.update_invoice(
                sample_invoice.id, InvoiceUpdateRequest(status="approved"), actor
            )
        assert update_exc.value.status_code == 403
        assert update_exc.value.error_code == "FINANCE_WRITE_FORBIDDEN"

        with pytest.raises(AppException) as pay_exc:
            await service.create_payment(
                sample_invoice.id,
                PaymentCreateRequest(
                    payment_date=date(2026, 11, 14),
                    amount=Decimal("50.00"),
                    method="bank_transfer",
                ),
                actor,
            )
        assert pay_exc.value.status_code == 403
        assert pay_exc.value.error_code == "FINANCE_WRITE_FORBIDDEN"
