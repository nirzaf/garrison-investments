from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.approval import Approval
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.approvals import ApprovalCreateRequest
from app.services.approval_service import ApprovalService
from app.utils.security import utc_now
from tests.password_fixtures import hash_fixture_password

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
        password_hash=hash_fixture_password(password),
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
                    project_id=project.id, user_id=pm.id, role_in_project="Group Project Manager"
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


async def test_generic_approval_creation_and_override_are_disabled() -> None:
    await skip_if_database_unavailable()
    director, director_password = await create_user("managing_director")
    submitter, submitter_password = await create_user("quantity_surveyor")

    async with create_test_client() as client:
        submitter_token = await login_for_token(client, submitter, submitter_password)
        director_token = await login_for_token(client, director, director_password)

        created = await client.post(
            "/api/v1/approvals",
            json={
                "request_type": "project_change",
                "request_id": str(uuid4()),
                "project_id": str(uuid4()),
                "title": "Change blockwork sequence",
                "comments": "Weather impact requires sequence change.",
            },
            headers={"Authorization": f"Bearer {submitter_token}"},
        )
        assert created.status_code == 403
        assert created.json()["error_code"] == "APPROVAL_TYPE_FORBIDDEN"

        overridden = await client.post(
            f"/api/v1/approvals/{uuid4()}/override",
            json={"decision": "approved", "reason": "Emergency site requirement"},
            headers={"Authorization": f"Bearer {director_token}"},
        )
        assert overridden.status_code == 403
        assert overridden.json()["error_code"] == "APPROVAL_OVERRIDE_FORBIDDEN"


async def test_material_request_approval_falls_back_only_to_company_director() -> None:
    await skip_if_database_unavailable()
    operations_director, _ = await create_user("operations_director")
    managing_director, _ = await create_user("managing_director")
    group_pm, _ = await create_user("group_project_manager")
    engineer, _ = await create_user("quantity_surveyor")
    project = await create_project(group_pm, engineer)

    async with AsyncSessionLocal() as session:
        actor = await session.get(User, managing_director.id)
        assert actor is not None
        approval = await ApprovalService(session).create_approval(
            ApprovalCreateRequest(
                request_type="material_request",
                request_id=uuid4(),
                project_id=project.id,
                title="Director submitted material request",
                amount=Decimal("50.00"),
                currency="USD",
            ),
            actor,
            internal=True,
        )

    assert approval.approver_id == operations_director.id

    async with AsyncSessionLocal() as session:
        notification = await session.scalar(
            select(Notification).where(
                Notification.user_id == operations_director.id,
                Notification.reference_id == approval.id,
                Notification.title == "Approval pending",
            )
        )

    assert notification is not None
    assert (
        notification.body == "Director submitted material request is waiting for your approval.\n\n"
        "Open approval: https://portal.example.com/approvals?tab=workflow&approvalId="
        f"{approval.id}"
    )


async def test_approval_amounts_follow_financial_permission_and_current_project_scope() -> None:
    await skip_if_database_unavailable()
    manager, manager_password = await create_user("group_project_manager")
    engineer, engineer_password = await create_user("mep_project_manager")
    assigned = await create_project(manager, engineer)
    director, _ = await create_user("managing_director")
    other = await create_project(director, engineer)
    now = utc_now()

    async with AsyncSessionLocal() as session:
        records = [
            Approval(
                request_type="material_request",
                request_id=uuid4(),
                project_id=project_id,
                submitter_id=user_id,
                status="cancelled",
                title="Historical material request",
                amount=Decimal("50.00"),
                currency="LKR",
                submitted_at=now,
                due_at=now + timedelta(days=1),
            )
            for user_id, project_id in (
                (manager.id, assigned.id),
                (manager.id, other.id),
                (engineer.id, assigned.id),
            )
        ]
        session.add_all(records)
        await session.commit()
        ids = [str(record.id) for record in records]

    async with create_test_client() as client:
        for user, password, visible_ids in (
            (manager, manager_password, ids[:2]),
            (engineer, engineer_password, ids[2:]),
        ):
            token = await login_for_token(client, user, password)
            headers = {"Authorization": f"Bearer {token}"}
            outbox = await client.get(
                "/api/v1/approvals", params={"box": "outbox"}, headers=headers
            )
            assert outbox.status_code == 200
            rows = {row["id"]: row for row in outbox.json()["items"]}
            assert set(rows) == set(visible_ids)
            for record_id in visible_ids:
                expected = ("50.00", "LKR") if record_id == ids[0] else (None, None)
                detail = await client.get(f"/api/v1/approvals/{record_id}", headers=headers)
                assert detail.status_code == 200
                for row in (rows[record_id], detail.json()):
                    assert (row["amount"], row["currency"]) == expected


async def test_material_director_threshold_settings_reject_invalid_values(monkeypatch) -> None:
    from pydantic import ValidationError

    from app.config import Settings
    from app.services.approval_service import required_material_stages

    monkeypatch.setenv("MATERIAL_OPERATIONS_APPROVAL_THRESHOLD", "")
    monkeypatch.setenv("MATERIAL_MD_APPROVAL_THRESHOLD", "")
    assert Settings().material_operations_approval_threshold is None
    with pytest.raises(ValidationError):
        Settings(material_operations_approval_threshold=Decimal("-1"))
    with pytest.raises(ValidationError):
        Settings(
            material_operations_approval_threshold=Decimal("5000"),
            material_md_approval_threshold=Decimal("1000"),
        )
    policy = Settings(material_operations_approval_threshold=Decimal("1000"))
    monkeypatch.setattr("app.services.approval_service.get_settings", lambda: policy)
    assert required_material_stages(None) == (1, 2)
    assert required_material_stages(Decimal("0")) == (1, 2)
