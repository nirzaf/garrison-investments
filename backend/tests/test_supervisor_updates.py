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


@pytest.mark.parametrize("supervisor_role", ["site_supervisor", "senior_site_supervisor"])
async def test_supervisor_requires_photo_and_separate_site_confirmations(
    supervisor_role: str,
) -> None:
    await skip_if_database_unavailable()
    from tests.test_daily_reports import report_payload, setup_project_team
    from tests.test_photos import jpeg_bytes

    async with create_test_client() as client:
        team = await setup_project_team(
            client,
            confirm_progress=False,
            quantities=True,
            supervisor_role=supervisor_role,
        )
        owner = {"Authorization": f"Bearer {team['supervisor_token']}"}
        qs = {"Authorization": f"Bearer {team['engineer_token']}"}
        engineer = {"Authorization": f"Bearer {team['progress_reviewer_token']}"}
        director = {"Authorization": f"Bearer {team['op_token']}"}
        project_id = team["project_id"]
        update_id = team["supervisor_update_id"]
        path = f"/api/v1/supervisor-updates/{update_id}"

        without_photo = await client.post(
            f"{path}/submit", json={"expected_revision": 1}, headers=owner
        )
        assert without_photo.status_code == 422
        assert without_photo.json()["error_code"] == "SITE_PROGRESS_PHOTO_REQUIRED"
        image = await client.post(
            "/api/v1/photos/upload",
            files={"files": ("progress.jpg", jpeg_bytes(), "image/jpeg")},
            data={"entity_type": "supervisor_update", "entity_id": update_id},
            headers=owner,
        )
        assert image.status_code == 201, image.text
        submitted = await client.post(
            f"{path}/submit", json={"expected_revision": 1}, headers=owner
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "pending_qs"

        pending = await client.get(
            "/api/v1/supervisor-updates", params={"review_only": "true"}, headers=qs
        )
        assert [row["id"] for row in pending.json()["items"]] == [update_id]
        decision = {"expected_submission_revision": 1, "decision": "approved"}
        for headers, stage in (
            (engineer, "engineer"),
            (owner, "qs"),
            (director, "engineer"),
            (qs, "engineer"),
        ):
            forbidden = await client.post(
                f"{path}/review", json={**decision, "stage": stage}, headers=headers
            )
            assert forbidden.status_code in {403, 409}, forbidden.text
        verified_qs = await client.post(
            f"{path}/review", json={**decision, "stage": "qs"}, headers=qs
        )
        assert verified_qs.status_code == 200, verified_qs.text
        assert verified_qs.json()["status"] == "pending_engineer"

        report = await client.post(
            "/api/v1/reports", json=report_payload(project_id, update_id), headers=qs
        )
        assert report.status_code == 201, report.text
        premature = await client.post(f"/api/v1/reports/{report.json()['id']}/submit", headers=qs)
        assert premature.status_code == 409
        assert premature.json()["error_code"] == "SUPERVISOR_UPDATE_NOT_CONFIRMED"

        returned = await client.post(
            f"{path}/review",
            json={
                **decision,
                "stage": "engineer",
                "decision": "returned",
                "comments": "Check the work scope.",
            },
            headers=engineer,
        )
        assert returned.status_code == 200, returned.text
        history = await client.get(f"{path}/submissions", headers=owner)
        correction = await client.put(
            path,
            json={
                **history.json()[0]["requirements"],
                "expected_revision": returned.json()["revision"],
                "activity_scope": "Corrected work scope",
            },
            headers=owner,
        )
        assert correction.status_code == 200, correction.text
        retained = await client.delete(f"/api/v1/photos/{image.json()[0]['id']}", headers=owner)
        assert retained.status_code == 409
        assert retained.json()["error_code"] == "PHOTO_RETAINED_EVIDENCE"
        resubmitted = await client.post(
            f"{path}/submit",
            json={"expected_revision": correction.json()["revision"]},
            headers=owner,
        )
        assert resubmitted.status_code == 200, resubmitted.text
        assert (resubmitted.json()["status"], resubmitted.json()["submission_revision"]) == (
            "pending_qs",
            2,
        )

        stale = await client.post(f"{path}/review", json={**decision, "stage": "qs"}, headers=qs)
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "SUBMISSION_REVISION_CONFLICT"
        for stage, headers in (("qs", qs), ("engineer", engineer)):
            approved = await client.post(
                f"{path}/review",
                json={**decision, "expected_submission_revision": 2, "stage": stage},
                headers=headers,
            )
            assert approved.status_code == 200, approved.text
        history = await client.get(f"{path}/submissions", headers=owner)
        assert [row["engineer_decision"] for row in history.json()] == ["approved", "returned"]

        final = await client.post(f"/api/v1/reports/{report.json()['id']}/submit", headers=qs)
        assert final.status_code == 200, final.text
        no_project = await client.get("/api/v1/supervisor-updates", headers=qs)
        assert no_project.status_code == 422
        assert no_project.json()["error_code"] == "SUPERVISOR_UPDATE_PROJECT_REQUIRED"
        other = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": str(uuid4()), "status": "draft"},
            headers=qs,
        )
        assert other.status_code == 404


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
