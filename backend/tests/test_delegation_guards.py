"""H2 — delegation must not hand decision power to an unqualified or interested user."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password, utc_now

pytestmark = pytest.mark.asyncio

PASSWORD = "Start123!"


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def create_user(role: str, *, active: bool = True) -> User:
    user = User(
        email=f"delegate-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Delegate {uuid4().hex[:4]}",
        role=role,
        employee_code=f"DEL-{uuid4().hex[:8]}",
        phone="+97455550555",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=active,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user


async def login(user: User) -> str:
    async with create_test_client() as client:
        challenge = (
            await client.post(
                "/api/v1/auth/login", json={"email": user.email, "password": PASSWORD}
            )
        ).json()
        response = await client.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
        )
        assert response.status_code == 200, response.text
        return str(response.json()["access_token"])


async def create_project(members: list[User]) -> Project:
    async with AsyncSessionLocal() as session:
        project = Project(
            name=f"Delegation {uuid4().hex[:6]}",
            code=f"DEL-{uuid4().hex[:6]}",
            location="Doha",
            description="Delegation test project",
            scope_of_work="Delegation test scope",
            status="active",
            budget_amount=Decimal("100000.00"),
            start_date=utc_now().date(),
            target_end_date=utc_now().date(),
            client_name="Test Client",
            contract_number=f"C-{uuid4().hex[:6]}",
            progress_percentage=Decimal("10.00"),
            created_by=members[0].id,
        )
        session.add(project)
        await session.flush()
        session.add_all(
            ProjectMember(
                project_id=project.id,
                user_id=member.id,
                role_in_project=member.role.replace("_", " ").title(),
            )
            for member in members
        )
        await session.commit()
        await session.refresh(project)
    return project


async def create_approval(
    *,
    request_type: str,
    approver: User,
    submitter: User | None = None,
    project_id: UUID | None = None,
) -> Approval:
    now = utc_now()
    approval = Approval(
        request_type=request_type,
        request_id=uuid4(),
        project_id=project_id,
        submitter_id=submitter.id if submitter else None,
        approver_id=approver.id,
        status="pending",
        title=f"{request_type} delegation test",
        submitted_at=now,
        due_at=now + timedelta(days=3),
    )
    async with AsyncSessionLocal() as session:
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
    return approval


async def delegate(token: str, approval_id: UUID, target: UUID) -> httpx.Response:
    async with create_test_client() as client:
        return await client.post(
            f"/api/v1/approvals/{approval_id}/delegate",
            headers={"Authorization": f"Bearer {token}"},
            json={"delegated_to_id": str(target), "reason": "Covering while on leave."},
        )


async def candidates(token: str, approval_id: UUID) -> httpx.Response:
    async with create_test_client() as client:
        return await client.get(
            f"/api/v1/approvals/{approval_id}/delegates",
            headers={"Authorization": f"Bearer {token}"},
        )


async def test_delegating_to_the_submitter_is_rejected() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    engineer = await create_user("civil_engineer")
    approval = await create_approval(
        request_type="project_change", approver=manager, submitter=engineer
    )
    token = await login(manager)

    response = await delegate(token, approval.id, engineer.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_TO_SUBMITTER_FORBIDDEN"


async def test_self_delegation_is_rejected() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    approval = await create_approval(request_type="project_change", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, manager.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_TO_SELF_FORBIDDEN"


@pytest.mark.parametrize(
    "role", ["civil_engineer", "civil_supervisor", "store_keeper", "accounts", "project_manager"]
)
async def test_invoice_delegation_requires_an_invoice_approver_role(role: str) -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    outsider = await create_user(role)
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, outsider.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_ROLE_FORBIDDEN"


async def test_invoice_delegation_to_another_operation_manager_succeeds() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    peer = await create_user("operation_manager")
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, peer.id)

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "delegated"
    assert response.json()["delegated_to_id"] == str(peer.id)
    # The delegate can now decide, which is the whole point of a qualified delegation.
    peer_token = await login(peer)
    async with create_test_client() as client:
        decided = await client.post(
            f"/api/v1/approvals/{approval.id}/approve",
            headers={"Authorization": f"Bearer {peer_token}"},
            json={"comments": "Approved on behalf of the Operation Manager."},
        )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"


async def test_daily_report_delegation_accepts_general_manager() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    general = await create_user("general_manager")
    approval = await create_approval(request_type="daily_report", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, general.id)

    assert response.status_code == 200, response.text


async def test_project_manager_delegate_must_belong_to_the_project() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    member_pm = await create_user("project_manager")
    foreign_pm = await create_user("project_manager")
    project = await create_project([manager, member_pm])
    approval = await create_approval(
        request_type="material_request", approver=manager, project_id=project.id
    )
    token = await login(manager)

    rejected = await delegate(token, approval.id, foreign_pm.id)
    accepted = await delegate(token, approval.id, member_pm.id)

    assert rejected.status_code == 403
    assert rejected.json()["error_code"] == "DELEGATION_PROJECT_FORBIDDEN"
    assert accepted.status_code == 200, accepted.text


async def test_unscoped_approval_cannot_be_delegated_to_a_project_manager() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    project_manager = await create_user("project_manager")
    approval = await create_approval(request_type="document", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, project_manager.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_PROJECT_FORBIDDEN"


async def test_inactive_delegate_is_not_found() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    inactive = await create_user("operation_manager", active=False)
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, inactive.id)

    assert response.status_code == 404


async def test_candidate_list_matches_the_delegation_guard() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    peer = await create_user("operation_manager")
    admin = await create_user("admin")
    member_pm = await create_user("project_manager")
    foreign_pm = await create_user("project_manager")
    engineer = await create_user("civil_engineer")
    project = await create_project([manager, member_pm, engineer])
    approval = await create_approval(
        request_type="material_request",
        approver=manager,
        submitter=engineer,
        project_id=project.id,
    )
    token = await login(manager)

    response = await candidates(token, approval.id)

    assert response.status_code == 200, response.text
    body = response.json()
    returned = {item["id"] for item in body["items"]}
    assert body["total"] == len(body["items"])
    # Project Managers are narrowed to this project's members, so that slice is exact.
    assert str(member_pm.id) in returned
    assert str(foreign_pm.id) not in returned
    # Members rank first so a large company directory cannot crowd them out of the cap.
    assert body["items"][0]["id"] == str(member_pm.id)
    # The acting approver, the submitter and ineligible roles are never offered.
    assert str(manager.id) not in returned
    assert str(engineer.id) not in returned
    assert {item["role"] for item in body["items"]} <= {
        "admin",
        "operation_manager",
        "project_manager",
    }
    # No false offers: every candidate the picker shows must pass the delegation guard.
    for item in body["items"]:
        fresh = await create_approval(
            request_type="material_request", approver=manager, project_id=project.id
        )
        accepted = await delegate(token, fresh.id, UUID(item["id"]))
        assert accepted.status_code == 200, accepted.text
    # Company-wide peers stay eligible even when the capped list does not surface them.
    for company_wide in (peer, admin):
        fresh = await create_approval(
            request_type="material_request", approver=manager, project_id=project.id
        )
        accepted = await delegate(token, fresh.id, company_wide.id)
        assert accepted.status_code == 200, accepted.text


async def test_unscoped_invoice_candidates_exclude_project_managers() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    await create_user("project_manager")
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await candidates(token, approval.id)

    assert response.status_code == 200
    assert {item["role"] for item in response.json()["items"]} <= {"admin", "operation_manager"}


async def test_candidate_list_requires_acting_rights() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operation_manager")
    bystander = await create_user("operation_manager")
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(bystander)

    response = await candidates(token, approval.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"
