from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_task import ProjectTask
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.projects import ProjectTaskUpdateRequest, ProjectUpdateRequest
from app.services.project_service import ProjectService
from tests.concurrency_helpers import error_codes, race_sessions, status_counts
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
                employee_code=f"PRJ-{uuid4().hex[:8]}",
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
        "name": f"Tower Works {uuid4().hex[:6]}",
        "scope_of_work": "Civil works and fit-out scope.",
        "target_end_date": "2026-12-31",
        "location": "Doha",
        "client_name": "Garrison Client",
        "contract_number": f"CN-{uuid4().hex[:6]}",
        "milestones": [
            {
                "name": "Mobilization",
                "discipline": "civil",
                "planned_start_date": "2026-06-01",
                "planned_end_date": "2026-06-15",
                "sort_order": 1,
            }
        ],
        "boq_items": [
            {
                "item_code": "BOQ-001",
                "description": "Site preparation",
                "discipline": "civil",
                "phase": "Mobilization",
                "milestone_name": "Mobilization",
                "unit": "lot",
                "planned_quantity": "1",
                "unit_rate": "1500",
            }
        ],
    }


async def test_operation_manager_creates_project_with_boq_and_timeline() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        payload = project_payload()
        payload["milestones"][0].update({"planned_start_date": None, "planned_end_date": None})
        create_response = await client.post(
            "/api/v1/projects",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )

        assert create_response.status_code == 201
        project = create_response.json()
        assert project["code"]

        detail_response = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert len(detail["boq_items"]) == 1
        assert len(detail["milestones"]) == 1
        assert detail["boq_items"][0]["milestone_id"] == detail["milestones"][0]["id"]
        assert detail["milestones"][0]["planned_start_date"] is None
        assert detail["is_read_only"] is False

        timeline_response = await client.get(
            f"/api/v1/projects/{project['id']}/timeline",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert timeline_response.status_code == 200
        assert timeline_response.json()["milestones"][0]["name"] == "Mobilization"


async def test_assigned_engineer_can_read_assigned_project_only() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")
    engineer_email, engineer_password = await create_user("civil_engineer")
    inactive_email, _ = await create_user("civil_engineer")
    async with AsyncSessionLocal() as session:
        inactive = await UserRepository(session).get_by_email(inactive_email)
        assert inactive is not None
        inactive.is_active = False
        inactive_id = str(inactive.id)
        await session.commit()

    async with create_test_client() as client:
        op_token = await login_for_token(client, op_email, op_password)
        engineer_token = await login_for_token(client, engineer_email, engineer_password)
        project = (
            await client.post(
                "/api/v1/projects",
                json=project_payload(),
                headers={"Authorization": f"Bearer {op_token}"},
            )
        ).json()
        me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assign_response = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": me.json()["id"], "role_in_project": "site_engineer"},
            headers={"Authorization": f"Bearer {op_token}"},
        )

        assert assign_response.status_code == 201
        assert assign_response.json()["user_name"] == "civil_engineer User"

        detail_response = await client.get(
            f"/api/v1/projects/{project['id']}",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )

        assert detail_response.status_code == 200
        assert detail_response.json()["revision"] == project["revision"] + 1
        assert detail_response.json()["members"][0]["user_name"] == "civil_engineer User"

        denied_edit = await client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Unauthorized change"},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        denied_assign = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": me.json()["id"]},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        duplicate_assign = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": me.json()["id"]},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert denied_edit.status_code == denied_assign.status_code == 403
        assert duplicate_assign.status_code == 409
        inactive_assign = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": inactive_id},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert inactive_assign.status_code == 404
        task = await client.post(
            f"/api/v1/projects/{project['id']}/tasks",
            json={"name": "Assigned project task"},
            headers={"Authorization": f"Bearer {op_token}"},
        )
        assert task.status_code == 201
        denied_task_edit = await client.patch(
            f"/api/v1/projects/{project['id']}/tasks/{task.json()['id']}",
            json={"name": "Unauthorized task edit", "expected_revision": 1},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert denied_task_edit.status_code == 403


@pytest.mark.parametrize("final_status", ["completed", "cancelled"])
async def test_closed_project_is_read_only(final_status: str) -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("operation_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        project = (
            await client.post(
                "/api/v1/projects",
                json=project_payload(),
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()

        complete_response = await client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"status": final_status, "actual_end_date": "2026-12-30"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert complete_response.status_code == 200

        update_response = await client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "Changed Name"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert update_response.status_code == 409
        actor = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assignment = await client.post(
            f"/api/v1/projects/{project['id']}/members",
            json={"user_id": actor.json()["id"]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert assignment.status_code == 409


async def test_project_setup_rejects_invalid_rows_before_persisting() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("operation_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        headers = {"Authorization": f"Bearer {token}"}
        for milestone_fields, boq_fields, expected_field in (
            ({"planned_start_date": "invalid"}, {}, "planned_start_date"),
            ({"planned_start_date": "2026-08-01"}, {}, "planned_end_date"),
            ({}, {"milestone_name": "Unknown"}, "milestone_name"),
            ({}, {"item_code": " boq-001 "}, "item_code"),
            ({}, {"planned_quantity": "0"}, "planned_quantity"),
            ({}, {"unit_rate": "-1"}, "unit_rate"),
            ({}, {"description": " "}, "description"),
            ({}, {"planned_quantity": "99999999999", "unit_rate": "999999999999"}, "unit_rate"),
        ):
            payload = project_payload()
            payload["milestones"][0].update(milestone_fields)
            payload["boq_items"].append(
                {**payload["boq_items"][0], "item_code": "BOQ-002", **boq_fields}
            )
            result = await client.post("/api/v1/projects", json=payload, headers=headers)
            assert result.status_code == 422, result.text
            issues = result.json()["errors"]
            fields = [issue.get("field") or ".".join(map(str, issue["loc"])) for issue in issues]
            assert any(field.endswith(expected_field) for field in fields)
            async with AsyncSessionLocal() as session:
                assert (
                    await session.scalar(select(Project.id).where(Project.name == payload["name"]))
                    is None
                )

        payload = project_payload()
        payload["milestones"].append({"name": " mobilization "})
        result = await client.post("/api/v1/projects", json=payload, headers=headers)
        assert result.status_code == 422
        assert result.json()["errors"][0]["field"] == "milestones.1.name"


async def test_multiple_milestones_and_boq_rows_preserve_decimal_values() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("general_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        headers = {"Authorization": f"Bearer {token}"}
        payload = project_payload()
        payload["milestones"] = [{"name": name} for name in ("Site prep", "Structural", "Finishes")]
        payload["boq_items"] = [
            {
                **payload["boq_items"][0],
                "item_code": f"BOQ-{index:03d}",
                "milestone_name": payload["milestones"][index // 2]["name"],
                "planned_quantity": "1.105",
                "unit_rate": "4.60",
            }
            for index in range(6)
        ]
        result = await client.post("/api/v1/projects", json=payload, headers=headers)
        assert result.status_code == 201, result.text
        detail = await client.get(f"/api/v1/projects/{result.json()['id']}", headers=headers)
        assert detail.status_code == 200
        milestones = detail.json()["milestones"]
        boq = detail.json()["boq_items"]
        assert len(milestones) == 3 and len(boq) == 6
        for index, row in enumerate(boq):
            assert row["milestone_id"] == milestones[index // 2]["id"]
            assert Decimal(row["planned_quantity"]) == Decimal("1.105")
            assert Decimal(row["unit_rate"]) == Decimal("4.60")
            assert Decimal(row["planned_amount"]) == Decimal("5.08")


async def test_project_edit_can_clear_optional_fields_and_audits_only_changed_fields() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("operation_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        headers = {"Authorization": f"Bearer {token}"}
        project = (
            await client.post("/api/v1/projects", json=project_payload(), headers=headers)
        ).json()
        url = f"/api/v1/projects/{project['id']}"
        update = await client.patch(
            url,
            json={
                "expected_revision": project["revision"],
                "location": None,
                "name": " Updated name ",
            },
            headers=headers,
        )
        assert update.status_code == 200, update.text
        data = update.json()
        assert data["location"] is None and data["client_name"] == project["client_name"]
        assert data["name"] == "Updated name" and data["revision"] == project["revision"] + 1
        for payload in (
            {"status": None},
            {"target_end_date": None},
            {"name": "  "},
            {"revision": 2},
        ):
            invalid = await client.patch(url, json=payload, headers=headers)
            assert invalid.status_code == 422
        stale = await client.patch(
            url,
            json={"expected_revision": project["revision"], "location": "Changed"},
            headers=headers,
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "PROJECT_REVISION_CONFLICT"

    async with AsyncSessionLocal() as session:
        audit = await session.scalar(
            select(ActivityLog).where(
                ActivityLog.entity_id == UUID(project["id"]),
                ActivityLog.action == "projects.updated",
            )
        )
        assert audit is not None
        assert audit.old_values == {
            "name": project["name"],
            "location": project["location"],
            "revision": 1,
        }
        assert audit.new_values == {"name": "Updated name", "location": None, "revision": 2}


async def test_project_edits_from_same_revision_serialize() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("operation_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        response = await client.post(
            "/api/v1/projects", json=project_payload(), headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 201
        project = response.json()

    async def save(session: AsyncSession, name: str) -> int:
        actor = await UserRepository(session).get_by_email(credentials[0])
        assert actor is not None
        await ProjectService(session).update_project(
            UUID(project["id"]),
            ProjectUpdateRequest(name=name, expected_revision=project["revision"]),
            actor,
        )
        return 200

    results = await race_sessions(
        lambda session: save(session, "Edit one"), lambda session: save(session, "Edit two")
    )
    assert status_counts(results) == {200: 1, 409: 1}
    assert error_codes(results) == ["PROJECT_REVISION_CONFLICT"]


async def test_task_updates_keep_each_date_range_and_require_current_revision() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("operation_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        headers = {"Authorization": f"Bearer {token}"}
        project = (
            await client.post("/api/v1/projects", json=project_payload(), headers=headers)
        ).json()
        other = (
            await client.post("/api/v1/projects", json=project_payload(), headers=headers)
        ).json()
        url = f"/api/v1/projects/{project['id']}"
        foreign_url = f"/api/v1/projects/{other['id']}"
        created = await client.post(
            f"{url}/tasks",
            json={
                "name": "Early task",
                "baseline_start_date": "2026-06-01",
                "baseline_end_date": "2026-06-02",
            },
            headers=headers,
        )
        assert created.status_code == 201
        task = created.json()
        foreign = (
            await client.post(f"{foreign_url}/tasks", json={"name": "Other task"}, headers=headers)
        ).json()
        task_url = f"{url}/tasks/{task['id']}"
        for payload, code in (
            ({"dependency_task_id": task["id"]}, "PROJECT_TASK_DEPENDENCY_CYCLE"),
            ({"dependency_task_id": foreign["id"]}, "PROJECT_TASK_INVALID_DEPENDENCY"),
            ({"baseline_end_date": "2026-05-30"}, "PROJECT_DATE_ORDER"),
            ({"progress_percentage": "101"}, "VALIDATION_ERROR"),
        ):
            result = await client.patch(
                task_url, json={"expected_revision": task["revision"], **payload}, headers=headers
            )
            assert result.status_code == 422
            assert result.json()["error_code"] == code
        missing = await client.patch(task_url, json={"name": "Missing revision"}, headers=headers)
        assert missing.status_code == 422
        wrong_project = await client.patch(
            f"{foreign_url}/tasks/{task['id']}",
            json={"expected_revision": 1, "name": "Other project"},
            headers=headers,
        )
        assert wrong_project.status_code == 404
        update = await client.patch(
            task_url,
            json={
                "expected_revision": 1,
                "planned_start_date": "2026-06-03",
                "planned_end_date": "2026-06-04",
                "actual_start_date": "2026-06-05",
                "progress_percentage": "25.5",
                "status": "in_progress",
            },
            headers=headers,
        )
        assert update.status_code == 200, update.text
        stale = await client.patch(
            task_url, json={"expected_revision": 1, "name": "Stale rename"}, headers=headers
        )
        assert stale.status_code == 409
        timeline = await client.get(f"{url}/timeline", headers=headers)
        saved = timeline.json()["tasks"][0]
        assert saved["baseline_start_date"] == "2026-06-01"
        assert saved["planned_start_date"] == "2026-06-03"
        assert saved["actual_start_date"] == "2026-06-05" and saved["actual_end_date"] is None
        assert Decimal(saved["progress_percentage"]) == Decimal("25.50") and saved["revision"] == 2

        completed = await client.patch(url, json={"status": "completed"}, headers=headers)
        assert completed.status_code == 200
        locked = await client.patch(
            task_url, json={"expected_revision": 2, "name": "Final edit"}, headers=headers
        )
        assert locked.status_code == 409 and locked.json()["error_code"] == "PROJECT_READ_ONLY"


async def test_concurrent_reverse_dependencies_cannot_create_cycle() -> None:
    await skip_if_database_unavailable()
    credentials = await create_user("operation_manager")
    async with create_test_client() as client:
        token = await login_for_token(client, *credentials)
        headers = {"Authorization": f"Bearer {token}"}
        project = (
            await client.post("/api/v1/projects", json=project_payload(), headers=headers)
        ).json()
        project_id = UUID(project["id"])
        tasks = [
            UUID(
                (
                    await client.post(
                        f"/api/v1/projects/{project_id}/tasks", json={"name": name}, headers=headers
                    )
                ).json()["id"]
            )
            for name in ("First", "Second")
        ]

    async def set_dependency(session: AsyncSession, task_id: UUID, dependency_id: UUID) -> int:
        actor = await UserRepository(session).get_by_email(credentials[0])
        assert actor is not None
        await ProjectService(session).update_task(
            project_id,
            task_id,
            ProjectTaskUpdateRequest(expected_revision=1, dependency_task_id=dependency_id),
            actor,
        )
        return 200

    results = await race_sessions(
        lambda session: set_dependency(session, tasks[0], tasks[1]),
        lambda session: set_dependency(session, tasks[1], tasks[0]),
    )
    assert status_counts(results) == {200: 1, 422: 1}
    assert error_codes(results) == ["PROJECT_TASK_DEPENDENCY_CYCLE"]
    async with AsyncSessionLocal() as session:
        dependencies = (
            await session.scalars(
                select(ProjectTask.dependency_task_id).where(ProjectTask.id.in_(tasks))
            )
        ).all()
        assert dependencies.count(None) == 1
