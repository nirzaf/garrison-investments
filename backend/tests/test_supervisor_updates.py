from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.time import business_today
from tests.password_fixtures import hash_fixture_password

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def skip_if_database_unavailable() -> None:
    if not await check_database():
        pytest.skip("database is not available")


async def create_user(role: str, password: str = "Start123!") -> tuple[str, str]:
    email = f"{role}-{uuid4().hex}@example.com"
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(
            User(
                email=email,
                full_name=f"{role} User",
                role=role,
                employee_code=f"SUP-{uuid4().hex[:8]}",
                phone="+97455550000",
                designation=role.replace("_", " ").title(),
                password_hash=hash_fixture_password(password),
                must_change_password=False,
            )
        )
        await session.commit()
    return email, password


def create_test_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def login_for_token(client: httpx.AsyncClient, email: str, password: str) -> str:
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    challenge = login_response.json()
    verify_response = await client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


def project_payload() -> dict:
    return {
        "name": f"Supervisor Flow {uuid4().hex[:6]}",
        "scope_of_work": "Civil works.",
        "target_end_date": "2026-12-31",
        "milestones": [{"name": "Mobilization", "sort_order": 1}],
        "boq_items": [
            {
                "item_code": "BOQ-001",
                "description": "Site work",
                "unit": "lot",
                "planned_quantity": "1",
                "unit_rate": "100",
            }
        ],
    }


async def setup_assigned_supervisor_project(client: httpx.AsyncClient):
    op_email, op_password = await create_user("operations_director")
    supervisor_email, supervisor_password = await create_user("site_supervisor")
    engineer_email, engineer_password = await create_user("quantity_surveyor")
    op_token = await login_for_token(client, op_email, op_password)
    supervisor_token = await login_for_token(client, supervisor_email, supervisor_password)
    engineer_token = await login_for_token(client, engineer_email, engineer_password)
    project = (
        await client.post(
            "/api/v1/projects",
            json=project_payload(),
            headers={"Authorization": f"Bearer {op_token}"},
        )
    ).json()
    supervisor = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    engineer = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {engineer_token}"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": supervisor.json()["id"], "role_in_project": "site_supervisor"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer.json()["id"], "role_in_project": "quantity_surveyor"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    return project, supervisor_token, engineer_token


async def test_supervisor_can_create_and_submit_update_for_assigned_project() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        project, supervisor_token, engineer_token = await setup_assigned_supervisor_project(client)
        payload = {
            "project_id": project["id"],
            "update_date": str(business_today()),
            "day_type": "weekday",
            "work_location": "Zone A",
            "attendance_count": 12,
            "overtime_hours": "2",
            "progress_notes": "Completed shuttering.",
            "delay_notes": "No delays.",
            "required_notes": "Safety toolbox talk completed.",
            "attachment_refs": [{"name": "zone-a.jpg", "kind": "photo"}],
        }
        create_response = await client.post(
            "/api/v1/supervisor-updates",
            json=payload,
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )

        assert create_response.status_code == 201
        update = create_response.json()
        assert update["status"] == "draft"

        submit_response = await client.post(
            f"/api/v1/supervisor-updates/{update['id']}/submit",
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )

        assert submit_response.status_code == 200
        assert submit_response.json()["status"] == "submitted"

        list_response = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": project["id"], "status": "submitted"},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )

        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == update["id"]
        assert list_response.json()["items"][0]["status"] == "submitted"

        # A submit-only report author can select evidence for an assigned project,
        # but cannot enumerate updates across the company or inspect drafts.
        no_project = await client.get(
            "/api/v1/supervisor-updates",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert no_project.status_code == 422
        assert no_project.json()["error_code"] == "SUPERVISOR_UPDATE_PROJECT_REQUIRED"
        another_project = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": str(uuid4()), "status": "draft"},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert another_project.status_code == 404


async def test_supervisor_can_autosave_existing_draft_update() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        project, supervisor_token, _ = await setup_assigned_supervisor_project(client)
        payload = {
            "project_id": project["id"],
            "update_date": str(business_today()),
            "day_type": "weekday",
            "work_location": "Zone A",
            "attendance_count": 12,
            "overtime_hours": "2",
            "progress_notes": "Completed shuttering.",
            "delay_notes": "No delays.",
            "required_notes": "Safety toolbox talk completed.",
            "attachment_refs": [{"name": "zone-a.jpg", "kind": "photo"}],
        }
        update = (
            await client.post(
                "/api/v1/supervisor-updates",
                json=payload,
                headers={"Authorization": f"Bearer {supervisor_token}"},
            )
        ).json()
        autosave_response = await client.put(
            f"/api/v1/supervisor-updates/{update['id']}",
            json={**payload, "attendance_count": 14, "progress_notes": "Autosaved progress."},
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )

        assert autosave_response.status_code == 200
        autosaved = autosave_response.json()
        assert autosaved["attendance_count"] == 14
        assert autosaved["progress_notes"] == "Autosaved progress."


async def test_unassigned_supervisor_cannot_create_update() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operations_director")
    supervisor_email, supervisor_password = await create_user("site_supervisor")

    async with create_test_client() as client:
        op_token = await login_for_token(client, op_email, op_password)
        supervisor_token = await login_for_token(client, supervisor_email, supervisor_password)
        project = (
            await client.post(
                "/api/v1/projects",
                json=project_payload(),
                headers={"Authorization": f"Bearer {op_token}"},
            )
        ).json()
        response = await client.post(
            "/api/v1/supervisor-updates",
            json={
                "project_id": project["id"],
                "update_date": str(business_today()),
                "work_location": "Zone B",
                "attendance_count": 5,
                "progress_notes": "Started cleanup.",
                "required_notes": "No incidents.",
            },
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )

        assert response.status_code == 404


async def test_previous_date_update_is_blocked_for_supervisor() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        project, supervisor_token, _ = await setup_assigned_supervisor_project(client)
        response = await client.post(
            "/api/v1/supervisor-updates",
            json={
                "project_id": project["id"],
                "update_date": str(business_today() - timedelta(days=3)),
                "work_location": "Zone C",
                "attendance_count": 5,
                "progress_notes": "Late entry.",
                "required_notes": "Requires approval.",
            },
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )

        assert response.status_code == 409
