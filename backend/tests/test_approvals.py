from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.approvals import ApprovalCreateRequest
from app.services.approval_service import ApprovalService
from app.utils.security import hash_password

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frontend_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.utils.links.get_settings",
        lambda: SimpleNamespace(normalized_frontend_base_url="https://portal.example.com"),
    )


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_user(role: str, password: str = "Start123!") -> tuple[User, str]:
    user = User(
        email=f"approval-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Approval User",
        role=role,
        employee_code=f"APR-{uuid4().hex[:8]}",
        phone="+97455550444",
        designation=role.replace("_", " ").title(),
        password_hash=hash_password(password),
        must_change_password=False,
    )
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(user)
        await session.commit()
        await session.refresh(user)
    return user, password


async def create_project(pm: User, engineer: User) -> Project:
    async with AsyncSessionLocal() as session:
        project = Project(
            name=f"Approval Test {uuid4().hex[:6]}",
            code=f"APR-{uuid4().hex[:6]}",
            location="Doha",
            description="Approval test project",
            scope_of_work="Approval test scope",
            status="active",
            budget_amount=Decimal("100000.00"),
            start_date=date.today(),
            target_end_date=date.today(),
            client_name="Test Client",
            contract_number=f"C-{uuid4().hex[:6]}",
            progress_percentage=Decimal("10.00"),
            created_by=pm.id,
        )
        session.add(project)
        await session.flush()
        session.add_all(
            [
                ProjectMember(
                    project_id=project.id, user_id=pm.id, role_in_project="Project Manager"
                ),
                ProjectMember(
                    project_id=project.id, user_id=engineer.id, role_in_project="Engineer"
                ),
            ]
        )
        await session.commit()
        await session.refresh(project)
        return project


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, user: User, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={
            "challenge_id": challenge["challenge_id"],
            "otp": challenge.get("dev_otp") or "123456",
        },
    )
    return str(verify_response.json()["access_token"])


async def test_generic_approval_chain_delegation_rejection_and_override() -> None:
    await skip_if_database_unavailable()
    admin, admin_password = await create_user("admin")
    operation_manager, op_password = await create_user("operation_manager")
    project_manager, pm_password = await create_user("project_manager")
    engineer, engineer_password = await create_user("civil_engineer")
    project = await create_project(project_manager, engineer)

    async with create_test_client() as client:
        engineer_token = await login_for_token(client, engineer, engineer_password)
        pm_token = await login_for_token(client, project_manager, pm_password)
        op_token = await login_for_token(client, operation_manager, op_password)
        admin_token = await login_for_token(client, admin, admin_password)

        created = await client.post(
            "/api/v1/approvals",
            json={
                "request_type": "project_change",
                "request_id": str(uuid4()),
                "project_id": str(project.id),
                "title": "Change blockwork sequence",
                "comments": "Weather impact requires sequence change.",
            },
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert created.status_code == 201
        approval = created.json()
        assert approval["approver_id"] == str(project_manager.id)

        inbox = await client.get(
            "/api/v1/approvals",
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert inbox.status_code == 200
        assert any(item["id"] == approval["id"] for item in inbox.json()["items"])

        blocked_engineer_inbox = await client.get(
            "/api/v1/approvals",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked_engineer_inbox.status_code == 403

        delegated = await client.post(
            f"/api/v1/approvals/{approval['id']}/delegate",
            json={"delegated_to_id": str(operation_manager.id), "reason": "PM is on leave"},
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert delegated.status_code == 200
        assert delegated.json()["delegated_to_id"] == str(operation_manager.id)

        missing_reason = await client.post(
            f"/api/v1/approvals/{approval['id']}/reject",
            json={"comments": ""},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert missing_reason.status_code == 422

        rejected = await client.post(
            f"/api/v1/approvals/{approval['id']}/reject",
            json={"comments": "Rejected for UAT validation."},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"

        blocked_entity_approval = await client.post(
            "/api/v1/approvals",
            json={
                "request_type": "material_request",
                "request_id": str(uuid4()),
                "project_id": str(project.id),
                "title": "Direct material request approval",
                "amount": "1500.00",
                "currency": "USD",
            },
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked_entity_approval.status_code == 403
        assert blocked_entity_approval.json()["error_code"] == "APPROVAL_TYPE_FORBIDDEN"

        high_value = await client.post(
            "/api/v1/approvals",
            json={
                "request_type": "project_change",
                "request_id": str(uuid4()),
                "project_id": str(project.id),
                "title": "High priority sequence override",
                "amount": "1500.00",
                "currency": "USD",
            },
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert high_value.status_code == 201

        overridden = await client.post(
            f"/api/v1/approvals/{high_value.json()['id']}/override",
            json={"decision": "approved", "reason": "Emergency site requirement"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert overridden.status_code == 200
        assert overridden.json()["status"] == "override_approved"


async def test_project_manager_material_request_approval_routes_to_operations() -> None:
    await skip_if_database_unavailable()
    operation_manager, _ = await create_user("operation_manager")
    project_manager, _ = await create_user("project_manager")
    engineer, _ = await create_user("civil_engineer")
    project = await create_project(project_manager, engineer)

    async with AsyncSessionLocal() as session:
        actor = await session.get(User, project_manager.id)
        approval = await ApprovalService(session).create_approval(
            ApprovalCreateRequest(
                request_type="material_request",
                request_id=uuid4(),
                project_id=project.id,
                title="PM submitted material request",
                amount=Decimal("50.00"),
                currency="USD",
            ),
            actor,
            internal=True,
        )

    assert approval.approver_id == operation_manager.id

    async with AsyncSessionLocal() as session:
        notification = await session.scalar(
            select(Notification).where(
                Notification.user_id == operation_manager.id,
                Notification.reference_id == approval.id,
                Notification.title == "Approval pending",
            )
        )

    assert notification is not None
    assert (
        notification.body
        == "PM submitted material request is waiting for your approval.\n\n"
        "Open approval: https://portal.example.com/approvals?tab=workflow&approvalId="
        f"{approval.id}"
    )
