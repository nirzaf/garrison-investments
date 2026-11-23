"""Report and finance access for all ten roles across project scopes."""

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, engine
from app.models.daily_report import DailyReport
from app.models.finance import Invoice
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.utils.security import utc_now
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    login_for_token,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio

ROLES = (
    "managing_director",
    "operations_director",
    "group_project_manager",
    "mep_project_manager",
    "quantity_surveyor",
    "senior_site_supervisor",
    "site_supervisor",
    "hr_manager",
    "administrative_executive",
)
COMPANY_WIDE = ("managing_director", "operations_director")
FINANCE_READERS = (*COMPANY_WIDE, "group_project_manager")
SCOPES = ("own", "other", "none")
_MATRIX_CACHE: dict = {}

# GET /reports?project_id=... — list_reports()
REPORTS_LIST: dict[str, dict[str, int]] = {
    "managing_director": {"own": 200, "other": 200, "none": 200},
    "operations_director": {"own": 200, "other": 200, "none": 200},
    "group_project_manager": {"own": 200, "other": 404, "none": 200},
    "mep_project_manager": {"own": 200, "other": 404, "none": 200},
    "quantity_surveyor": {"own": 200, "other": 404, "none": 200},
    "senior_site_supervisor": {"own": 200, "other": 404, "none": 200},
    "site_supervisor": {"own": 200, "other": 404, "none": 200},
    "hr_manager": {"own": 403, "other": 403, "none": 403},
    "administrative_executive": {"own": 403, "other": 403, "none": 403},
}

# GET /reports/{id} — get_report() / _ensure_report_access()
REPORTS_GET: dict[str, dict[str, int]] = {
    "managing_director": {"own": 200, "other": 200},
    "operations_director": {"own": 200, "other": 200},
    "group_project_manager": {"own": 200, "other": 404},
    "mep_project_manager": {"own": 200, "other": 404},
    "quantity_surveyor": {"own": 200, "other": 404},
    "senior_site_supervisor": {"own": 404, "other": 404},
    "site_supervisor": {"own": 404, "other": 404},
    "hr_manager": {"own": 404, "other": 404},
    "administrative_executive": {"own": 404, "other": 404},
}

# GET /finance/invoices?project_id=... — list_invoices()
FINANCE_LIST: dict[str, dict[str, int]] = {
    "managing_director": {"own": 200, "other": 200, "none": 200},
    "operations_director": {"own": 200, "other": 200, "none": 200},
    "group_project_manager": {"own": 200, "other": 403, "none": 200},
    **{
        role: {"own": 403, "other": 403, "none": 403}
        for role in ROLES
        if role not in FINANCE_READERS
    },
}

# GET /finance/invoices/{id} — get_invoice() / _ensure_invoice_scope()
FINANCE_GET: dict[str, dict[str, int]] = {
    "managing_director": {"own": 200, "other": 200},
    "operations_director": {"own": 200, "other": 200},
    "group_project_manager": {"own": 200, "other": 403},
    **{role: {"own": 403, "other": 403} for role in ROLES if role not in FINANCE_READERS},
}


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def _project(created_by: UUID) -> Project:
    return Project(
        name=f"Authz Matrix {uuid4().hex[:6]}",
        code=f"AZ-{uuid4().hex[:6]}",
        location="Doha",
        description="Authorization matrix project",
        scope_of_work="Authorization matrix scope",
        status="active",
        budget_amount=Decimal("100000.00"),
        start_date=date.today(),
        target_end_date=date.today() + timedelta(days=30),
        client_name="Matrix Client",
        contract_number=f"C-{uuid4().hex[:6]}",
        progress_percentage=Decimal("10.00"),
        created_by=created_by,
    )


def _report(project_id: UUID, engineer_id: UUID) -> DailyReport:
    return DailyReport(
        project_id=project_id,
        engineer_id=engineer_id,
        report_date=utc_now().date(),
        work_location="Zone A",
        manpower_total=10,
        overtime_hours=Decimal("1.00"),
        work_completed="Matrix baseline work.",
        progress_percentage=Decimal("20.00"),
        safety_incidents=0,
        wir_status="passed",
        inspection_status="completed",
        next_day_plan="Continue.",
        supervisor_update_ids=[],
        photo_refs=[],
        attachment_refs=[],
        extra_fields={},
        status="draft",
    )


def _invoice(project_id: UUID, created_by: UUID) -> Invoice:
    return Invoice(
        invoice_number=f"INV-{uuid4().hex[:8]}",
        project_id=project_id,
        invoice_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        amount=Decimal("300.00"),
        tax_amount=Decimal("15.00"),
        total_amount=Decimal("315.00"),
        status="submitted",
        payment_status="unpaid",
        created_by=created_by,
    )


async def _user_id(session: AsyncSession, email: str) -> UUID:
    user_id = await session.scalar(select(User.id).where(User.email == email))
    assert user_id is not None, email
    return user_id


async def build_matrix() -> dict:
    """Two projects, one report and invoice each, with a token for all ten roles.

    Every matrix role is a member of the *own* project only. The other project has a
    single outsider engineer so its report exists but belongs to nobody in the matrix.

    The result is cached at module level: it is plain strings, so it stays valid across
    the per-test engine disposal and event loops, and 80 parametrised cases share one
    setup instead of creating 900 users.
    """
    if _MATRIX_CACHE:
        return _MATRIX_CACHE
    credentials = {role: await create_user(role) for role in ROLES}
    outsider_email, _ = await create_user("quantity_surveyor")

    async with AsyncSessionLocal() as session:
        user_ids = {
            role: await _user_id(session, email) for role, (email, _) in credentials.items()
        }
        outsider_id = await _user_id(session, outsider_email)
        director_id = user_ids["managing_director"]
        own = _project(director_id)
        other = _project(director_id)
        session.add_all([own, other])
        await session.flush()
        session.add_all(
            [
                ProjectMember(
                    project_id=own.id,
                    user_id=user_id,
                    role_in_project=role,
                )
                for role, user_id in user_ids.items()
            ]
        )
        own_report = _report(own.id, user_ids["quantity_surveyor"])
        other_report = _report(other.id, outsider_id)
        own_invoice = _invoice(own.id, director_id)
        other_invoice = _invoice(other.id, director_id)
        session.add_all([own_report, other_report, own_invoice, other_invoice])
        await session.commit()
        ids = {
            "own_project_id": str(own.id),
            "other_project_id": str(other.id),
            "own_report_id": str(own_report.id),
            "other_report_id": str(other_report.id),
            "own_invoice_id": str(own_invoice.id),
            "other_invoice_id": str(other_invoice.id),
        }

    async with create_test_client() as client:
        tokens = {
            role: await login_for_token(client, email, password)
            for role, (email, password) in credentials.items()
        }
    _MATRIX_CACHE.update({"tokens": tokens, **ids})
    return _MATRIX_CACHE


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("scope", SCOPES)
async def test_reports_list_matrix(role: str, scope: str) -> None:
    await skip_if_database_unavailable()
    matrix = await build_matrix()
    params = {} if scope == "none" else {"project_id": matrix[f"{scope}_project_id"]}

    async with create_test_client() as client:
        response = await client.get(
            "/api/v1/reports",
            params=params,
            headers={"Authorization": f"Bearer {matrix['tokens'][role]}"},
        )

    assert response.status_code == REPORTS_LIST[role][scope], (
        f"reports list {role}/{scope}: {response.status_code} {response.text}"
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("scope", ("own", "other"))
async def test_reports_get_matrix(role: str, scope: str) -> None:
    await skip_if_database_unavailable()
    matrix = await build_matrix()

    async with create_test_client() as client:
        response = await client.get(
            f"/api/v1/reports/{matrix[f'{scope}_report_id']}",
            headers={"Authorization": f"Bearer {matrix['tokens'][role]}"},
        )

    assert response.status_code == REPORTS_GET[role][scope], (
        f"reports get {role}/{scope}: {response.status_code} {response.text}"
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("scope", SCOPES)
async def test_finance_list_matrix(role: str, scope: str) -> None:
    await skip_if_database_unavailable()
    matrix = await build_matrix()
    params = {} if scope == "none" else {"project_id": matrix[f"{scope}_project_id"]}

    async with create_test_client() as client:
        response = await client.get(
            "/api/v1/finance/invoices",
            params=params,
            headers={"Authorization": f"Bearer {matrix['tokens'][role]}"},
        )

    assert response.status_code == FINANCE_LIST[role][scope], (
        f"finance list {role}/{scope}: {response.status_code} {response.text}"
    )


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("scope", ("own", "other"))
async def test_finance_get_matrix(role: str, scope: str) -> None:
    await skip_if_database_unavailable()
    matrix = await build_matrix()

    async with create_test_client() as client:
        response = await client.get(
            f"/api/v1/finance/invoices/{matrix[f'{scope}_invoice_id']}",
            headers={"Authorization": f"Bearer {matrix['tokens'][role]}"},
        )

    assert response.status_code == FINANCE_GET[role][scope], (
        f"finance get {role}/{scope}: {response.status_code} {response.text}"
    )


async def test_directors_see_both_projects_in_reports_list() -> None:
    """Only MD and OD have company-wide resource scope."""
    await skip_if_database_unavailable()
    matrix = await build_matrix()

    async with create_test_client() as client:
        for role in COMPANY_WIDE:
            for scope in ("own", "other"):
                response = await client.get(
                    "/api/v1/reports",
                    params={"project_id": matrix[f"{scope}_project_id"], "limit": 200},
                    headers={"Authorization": f"Bearer {matrix['tokens'][role]}"},
                )
                assert response.status_code == 200, (role, scope, response.text)
                ids = {item["id"] for item in response.json()["items"]}
                assert matrix[f"{scope}_report_id"] in ids, (role, scope)


async def test_group_project_manager_without_membership_sees_nothing() -> None:
    await skip_if_database_unavailable()
    # Build the data first so "sees nothing" is proven against a populated database.
    await build_matrix()
    email, password = await create_user("group_project_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, email, password)
        response = await client.get(
            "/api/v1/reports",
            headers={"Authorization": f"Bearer {token}"},
        )
        finance = await client.get(
            "/api/v1/finance/invoices",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert finance.status_code == 200
    assert finance.json() == {"items": [], "total": 0}
