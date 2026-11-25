"""H2 — delegation must not hand decision power to an unqualified or interested user."""

from datetime import timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.inventory import MaterialRequest
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import utc_now
from tests.password_fixtures import hash_fixture_password
from tests.test_finance import add_invoice

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
        password_hash=hash_fixture_password(PASSWORD),
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
    request_id: UUID | None = None,
) -> Approval:
    if request_id is None and request_type == "invoice":
        project = await create_project([approver])
        invoice = await add_invoice(project, Decimal("100"), status="submitted")
        request_id = invoice.id
    if request_id is None and request_type == "material_request":
        assert project_id is not None
        async with AsyncSessionLocal() as session:
            request = MaterialRequest(
                request_number=f"MR-{uuid4().hex[:12]}",
                project_id=project_id,
                requester_id=submitter.id if submitter else None,
                status="requested",
                total_estimated_cost=Decimal("0"),
            )
            session.add(request)
            await session.commit()
            request_id = request.id
    now = utc_now()
    approval = Approval(
        request_type=request_type,
        request_id=request_id or uuid4(),
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


async def candidates(
    token: str, approval_id: UUID, params: dict[str, str | int] | None = None
) -> httpx.Response:
    async with create_test_client() as client:
        return await client.get(
            f"/api/v1/approvals/{approval_id}/delegates",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )


async def test_delegating_to_the_submitter_is_rejected() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    engineer = await create_user("quantity_surveyor")
    project = await create_project([manager, engineer])
    approval = await create_approval(
        request_type="material_request",
        approver=manager,
        submitter=engineer,
        project_id=project.id,
    )
    token = await login(manager)

    response = await delegate(token, approval.id, engineer.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_TO_SUBMITTER_FORBIDDEN"


async def test_self_delegation_is_rejected() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    project = await create_project([manager])
    approval = await create_approval(
        request_type="material_request", approver=manager, project_id=project.id
    )
    token = await login(manager)

    response = await delegate(token, approval.id, manager.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "DELEGATION_TO_SELF_FORBIDDEN"


@pytest.mark.parametrize(
    "role",
    [
        "quantity_surveyor",
        "site_supervisor",
        "senior_site_supervisor",
        "administrative_executive",
        "group_project_manager",
    ],
)
async def test_invoice_delegation_is_disabled_for_every_target_role(role: str) -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    outsider = await create_user(role)
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, outsider.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"


async def test_invoice_delegation_is_disabled_even_for_another_director() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    peer = await create_user("operations_director")
    project = await create_project([manager, peer])
    invoice = await add_invoice(project, Decimal("100"), status="submitted")
    approval = await create_approval(
        request_type="invoice", approver=manager, project_id=project.id, request_id=invoice.id
    )
    token = await login(manager)

    response = await delegate(token, approval.id, peer.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"
    peer_token = await login(peer)
    async with create_test_client() as client:
        decided = await client.post(
            f"/api/v1/approvals/{approval.id}/approve",
            headers={"Authorization": f"Bearer {peer_token}"},
            json={"comments": "Approved on behalf of the Operations Director."},
        )
    assert decided.status_code == 403
    assert decided.json()["error_code"] == "APPROVAL_FORBIDDEN"


async def test_daily_report_approval_requires_its_own_workflow() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    general = await create_user("operations_director")
    approval = await create_approval(request_type="daily_report", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, general.id)

    assert response.status_code == 409
    assert response.json()["error_code"] == "APPROVAL_REQUIRES_OWNING_WORKFLOW"


async def test_project_managers_cannot_receive_material_fulfillment_authority() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    member_pm = await create_user("group_project_manager")
    foreign_pm = await create_user("group_project_manager")
    project = await create_project([manager, member_pm])
    approval = await create_approval(
        request_type="material_request", approver=manager, project_id=project.id
    )
    token = await login(manager)

    rejected = await delegate(token, approval.id, foreign_pm.id)
    member = await delegate(token, approval.id, member_pm.id)

    assert rejected.status_code == 403
    assert rejected.json()["error_code"] == "DELEGATION_ROLE_FORBIDDEN"
    assert member.status_code == 403
    assert member.json()["error_code"] == "DELEGATION_ROLE_FORBIDDEN"


async def test_generic_approval_cannot_be_delegated() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    group_pm = await create_user("group_project_manager")
    approval = await create_approval(request_type="project_change", approver=manager)
    token = await login(manager)

    response = await delegate(token, approval.id, group_pm.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"


async def test_inactive_delegate_is_not_found() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    inactive = await create_user("operations_director", active=False)
    project = await create_project([manager])
    approval = await create_approval(
        request_type="material_request", approver=manager, project_id=project.id
    )
    token = await login(manager)

    response = await delegate(token, approval.id, inactive.id)

    assert response.status_code == 404


async def test_candidate_list_matches_the_delegation_guard() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    peer = await create_user("operations_director")
    managing_director = await create_user("managing_director")
    member_pm = await create_user("group_project_manager")
    foreign_pm = await create_user("group_project_manager")
    engineer = await create_user("quantity_surveyor")
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
    assert body["total"] >= len(body["items"])
    # Only users with inventory:manage are selectable for material approvals.
    assert str(member_pm.id) not in returned
    assert str(foreign_pm.id) not in returned
    # The acting approver, the submitter and ineligible roles are never offered.
    assert str(manager.id) not in returned
    assert str(engineer.id) not in returned
    assert {item["role"] for item in body["items"]} <= {
        "managing_director",
        "operations_director",
    }
    page = await candidates(token, approval.id, params={"limit": 1})
    assert page.status_code == 200
    assert len(page.json()["items"]) == 1
    assert page.json()["total"] == body["total"]
    if page.json()["total"] > 1:
        next_page = await candidates(token, approval.id, params={"limit": 1, "offset": 1})
        assert next_page.status_code == 200
        assert next_page.json()["items"][0]["id"] != page.json()["items"][0]["id"]

    # Both eligible company roles remain discoverable by server-side search beyond page 1.
    for company_wide in (peer, managing_director):
        filtered = await candidates(
            token,
            approval.id,
            params={"search": company_wide.full_name, "limit": 10},
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert {candidate["id"] for candidate in filtered.json()["items"]} == {
            str(company_wide.id)
        }
        fresh = await create_approval(
            request_type="material_request", approver=manager, project_id=project.id
        )
        accepted = await delegate(token, fresh.id, company_wide.id)
        assert accepted.status_code == 200, accepted.text


async def test_invoice_delegation_candidate_list_is_disabled() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    await create_user("group_project_manager")
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(manager)

    response = await candidates(token, approval.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"


async def test_candidate_list_requires_acting_rights() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    bystander = await create_user("operations_director")
    approval = await create_approval(request_type="invoice", approver=manager)
    token = await login(bystander)

    response = await candidates(token, approval.id)

    assert response.status_code == 403
    assert response.json()["error_code"] == "APPROVAL_FORBIDDEN"


async def test_outbox_and_escalation_visibility_do_not_grant_decision_rights() -> None:
    await skip_if_database_unavailable()
    manager = await create_user("operations_director")
    oversight = await create_user("operations_director")
    submitter = await create_user("site_supervisor")
    stranger = await create_user("site_supervisor")
    project = await create_project([manager, submitter])
    approval = await create_approval(
        request_type="material_request",
        approver=manager,
        submitter=submitter,
        project_id=project.id,
    )
    async with AsyncSessionLocal() as session:
        row = await session.get(Approval, approval.id)
        assert row is not None
        row.status = "escalated"
        row.escalation_user_id = oversight.id
        await session.commit()
    async with create_test_client() as client:
        submitter_headers = {"Authorization": f"Bearer {await login(submitter)}"}
        outbox = await client.get(
            "/api/v1/approvals",
            params={"box": "outbox", "status_group": "open"},
            headers=submitter_headers,
        )
        assert outbox.status_code == 200
        assert [item["id"] for item in outbox.json()["items"]] == [str(approval.id)]
        assert not outbox.json()["items"][0]["allowed_actions"]
        assert (await client.get("/api/v1/approvals", headers=submitter_headers)).status_code == 403
        stranger_outbox = await client.get(
            "/api/v1/approvals",
            params={"box": "outbox"},
            headers={"Authorization": f"Bearer {await login(stranger)}"},
        )
        assert stranger_outbox.json()["items"] == []
        oversight_headers = {"Authorization": f"Bearer {await login(oversight)}"}
        inbox = await client.get(
            "/api/v1/approvals", params={"status_group": "open"}, headers=oversight_headers
        )
        items = inbox.json()["items"]
        visible_ids = {item["id"] for item in items}
        assert str(approval.id) in visible_ids
        assert all(not item["allowed_actions"] for item in items)
        decision = await client.post(
            f"/api/v1/approvals/{approval.id}/approve", json={}, headers=oversight_headers
        )
        assert decision.status_code == 403
