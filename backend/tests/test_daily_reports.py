import asyncio
from datetime import date, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.config import Settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.inventory import InventoryMovement
from app.models.report_export import ReportExport
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.tasks.email import _send_report_email
from app.tasks.outbox import _dispatch_task_outbox
from app.tasks.report import _generate_report_pdf
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
                employee_code=f"DR-{uuid4().hex[:8]}",
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
        "name": f"Daily Report Flow {uuid4().hex[:6]}",
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


async def setup_project_team(
    client: httpx.AsyncClient,
    *,
    confirm_progress: bool = True,
    quantities: bool = False,
    supervisor_role: str = "site_supervisor",
) -> dict[str, str]:
    from tests.test_photos import jpeg_bytes

    op_email, op_password = await create_user("operations_director")
    engineer_email, engineer_password = await create_user("quantity_surveyor")
    supervisor_email, supervisor_password = await create_user(supervisor_role)
    reviewer_email, reviewer_password = await create_user("mep_project_manager")
    manager_email, manager_password = await create_user("group_project_manager")
    non_submitter_email, non_submitter_password = await create_user("administrative_executive")
    op_token = await login_for_token(client, op_email, op_password)
    engineer_token = await login_for_token(client, engineer_email, engineer_password)
    supervisor_token = await login_for_token(client, supervisor_email, supervisor_password)
    progress_reviewer_token = await login_for_token(client, reviewer_email, reviewer_password)
    manager_token = await login_for_token(client, manager_email, manager_password)
    non_submitter_token = await login_for_token(client, non_submitter_email, non_submitter_password)
    project = (
        await client.post(
            "/api/v1/projects",
            json={**project_payload(), "status": "active"},
            headers={"Authorization": f"Bearer {op_token}"},
        )
    ).json()
    engineer = (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
    ).json()
    supervisor = (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )
    ).json()
    manager = (
        await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {manager_token}"},
        )
    ).json()
    await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": engineer["id"], "role_in_project": "quantity_surveyor"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": supervisor["id"], "role_in_project": "site_supervisor"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": manager["id"], "role_in_project": "group_project_manager"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    reviewer_headers = {"Authorization": f"Bearer {progress_reviewer_token}"}
    reviewer = (await client.get("/api/v1/auth/me", headers=reviewer_headers)).json()
    assigned = await client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"user_id": reviewer["id"], "role_in_project": "mep_project_manager"},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert assigned.is_success, assigned.text
    supervisor_update = (
        await client.post(
            "/api/v1/supervisor-updates",
            json={
                "project_id": project["id"],
                "update_date": str(business_today()),
                "day_type": "weekday",
                "work_location": "Zone A",
                "attendance_count": 8,
                "overtime_hours": "1",
                "activity_scope": "Civil works in Zone A",
                "remaining_work": "Inspect and backfill",
                "progress_notes": "Completed excavation.",
                "required_notes": "No incidents.",
                **({"completed_quantity": "25.000", "quantity_unit": "m3"} if quantities else {}),
            },
            headers={"Authorization": f"Bearer {supervisor_token}"},
        )
    ).json()
    if confirm_progress:
        supervisor_headers = {"Authorization": f"Bearer {supervisor_token}"}
        uploaded = await client.post(
            "/api/v1/photos/upload",
                data={
                    "entity_type": "supervisor_update",
                    "entity_id": supervisor_update["id"],
                    "classification": "operational",
                },
            files={"files": ("progress.jpg", jpeg_bytes(), "image/jpeg")},
            headers=supervisor_headers,
        )
        assert uploaded.status_code == 201, uploaded.text
        submitted = await client.post(
            f"/api/v1/supervisor-updates/{supervisor_update['id']}/submit",
            json={"expected_revision": supervisor_update["revision"]},
            headers=supervisor_headers,
        )
        assert submitted.status_code == 200, submitted.text
        decision = await client.post(
            f"/api/v1/supervisor-updates/{supervisor_update['id']}/review",
            json={"expected_submission_revision": 1, "stage": "engineer", "decision": "approved"},
            headers=reviewer_headers,
        )
        assert decision.status_code == 200, decision.text
    return {
        "project_id": project["id"],
        "project_code": project["code"],
        "engineer_token": engineer_token,
        "manager_token": manager_token,
        "non_submitter_token": non_submitter_token,
        "op_token": op_token,
        "supervisor_token": supervisor_token,
        "progress_reviewer_token": progress_reviewer_token,
        "supervisor_update_id": supervisor_update["id"],
    }


def report_payload(project_id: str, supervisor_update_id: str | None = None) -> dict:
    return {
        "project_id": project_id,
        "report_date": str(business_today()),
        "work_location": "Zone A",
        "manpower_total": 18,
        "overtime_hours": "2.5",
        "work_completed": "Excavation and blinding completed.",
        "progress_percentage": "35",
        "safety_incidents": 0,
        "safety_notes": "Toolbox talk completed.",
        "wir_status": "passed",
        "inspection_status": "completed",
        "delay_notes": "None.",
        "next_day_plan": "Start reinforcement fixing.",
        "supervisor_update_ids": [supervisor_update_id] if supervisor_update_id else [],
        "photo_refs": [{"name": "zone-a.jpg", "kind": "photo"}],
        "attachment_refs": [{"name": "inspection.pdf", "kind": "file"}],
        "manpower_entries": [{"trade": "Mason", "count": 10, "overtime_hours": "1"}],
        "equipment_entries": [
            {"equipment_name": "Excavator", "quantity": 1, "hours_used": "6", "remarks": "OK"}
        ],
        "material_consumption": [
            {"material_name": "Concrete", "unit": "m3", "quantity": "12", "remarks": "Blinding"}
        ],
    }


async def setup_report_consumption_stock(
    client: httpx.AsyncClient, project_id: str, inventory_manager_token: str
) -> dict:
    suffix = uuid4().hex[:6]
    supplier = (
        await client.post(
            "/api/v1/suppliers",
            json={
                "name": f"Concrete Supplier {suffix}",
                "category": "Civil",
                "rating": "A",
                "payment_terms": "30 days",
                "contact_person": "Supplier Contact",
                "phone": "+97455550666",
                "email": f"supplier-{suffix}@example.com",
                "address": "Industrial Area",
                "tax_registration_number": f"TAX-{suffix}",
                "tds_certificate_number": "TDS-001",
                "tds_expiry_date": "2027-05-16",
                "compliance_status": "compliant",
            },
            headers={"Authorization": f"Bearer {inventory_manager_token}"},
        )
    ).json()
    location = (
        await client.post(
            "/api/v1/inventory/locations",
            json={
                "name": f"Project Store {suffix}",
                "code": f"PS-{suffix}",
                "location_type": "project_site",
                "project_id": project_id,
                "address": "Site",
            },
            headers={"Authorization": f"Bearer {inventory_manager_token}"},
        )
    ).json()
    item = (
        await client.post(
            "/api/v1/inventory/items",
            json={
                "name": "Concrete",
                "item_code": f"CON-{suffix}",
                "category": "Civil",
                "item_type": "consumable",
                "unit": "m2",
                "minimum_stock": "5",
                "reorder_level": "5",
                "unit_cost": "12.50",
                "supplier_id": supplier["id"],
            },
            headers={"Authorization": f"Bearer {inventory_manager_token}"},
        )
    ).json()
    await client.post(
        "/api/v1/inventory/movements",
        json={
            "item_id": item["id"],
            "movement_type": "receive",
            "quantity": "20",
            "to_location_id": location["id"],
            "project_id": project_id,
            "notes": "Opening stock",
        },
        headers={"Authorization": f"Bearer {inventory_manager_token}"},
    )
    return {
        "inventory_manager_token": inventory_manager_token,
        "item_id": item["id"],
        "location_id": location["id"],
    }


async def test_engineer_can_save_and_submit_daily_report() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        create_response = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert create_response.status_code == 201
        report = create_response.json()
        assert report["status"] == "draft"
        assert report["report_number"] is None
        assert len(report["manpower_entries"]) == 1

        submit_response = await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert submit_response.status_code == 200
        submitted = submit_response.json()
        assert submitted["status"] == "submitted"
        assert submitted["report_number"].startswith(f"{setup['project_code']}-DR-")

        updates_response = await client.get(
            f"/api/v1/reports/{report['id']}/supervisor-updates",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert updates_response.status_code == 200
        assert any(
            update["id"] == setup["supervisor_update_id"] for update in updates_response.json()
        )


async def test_non_engineer_cannot_create_daily_report() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        response = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"]),
            headers={"Authorization": f"Bearer {setup['non_submitter_token']}"},
        )

        assert response.status_code == 403


async def test_rejected_report_can_resubmit_its_verified_supervisor_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {setup['engineer_token']}"}
        manager = {"Authorization": f"Bearer {setup['manager_token']}"}
        payload = report_payload(setup["project_id"], setup["supervisor_update_id"])
        created = await client.post("/api/v1/reports", json=payload, headers=engineer)
        assert created.status_code == 201
        url = f"/api/v1/reports/{created.json()['id']}"
        submitted = await client.post(f"{url}/submit", headers=engineer)
        assert submitted.status_code == 200

        first_draft = await client.post(
            "/api/v1/reports", json={**payload, "supervisor_update_ids": []}, headers=engineer
        )
        assert first_draft.status_code == 201
        next_business_day = date.fromisoformat(payload["report_date"]) + timedelta(days=1)
        monkeypatch.setattr("app.services.report_service.business_today", lambda: next_business_day)

        old_unsubmitted = await client.post(
            f"/api/v1/reports/{first_draft.json()['id']}/submit", headers=engineer
        )
        assert old_unsubmitted.status_code == 422
        assert old_unsubmitted.json()["error_code"] == "DAILY_REPORT_PAST_DATE_UNSUPPORTED"

        rejected = await client.post(f"{url}/reject", json={"comments": "Revise"}, headers=manager)
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "draft"
        payload["expected_revision"] = rejected.json()["revision"]

        evidence = await client.get(f"{url}/supervisor-updates", headers=manager)
        assert evidence.status_code == 200
        retained = evidence.json()[0]
        assert retained["verified_report_id"] == created.json()["id"]
        assert retained["verified_by_name"]
        removed = await client.put(
            url, json={**payload, "supervisor_update_ids": []}, headers=engineer
        )
        assert removed.status_code == 409

        updated = await client.put(
            url, json={**payload, "work_completed": "Revised"}, headers=engineer
        )
        assert updated.status_code == 200
        resubmitted = await client.post(f"{url}/submit", headers=engineer)
        assert resubmitted.status_code == 200, resubmitted.json()
        assert resubmitted.json()["report_number"] == submitted.json()["report_number"]
        assert resubmitted.json()["report_date"] == payload["report_date"]
        assert resubmitted.json()["supervisor_update_ids"] == payload["supervisor_update_ids"]
        evidence_after = await client.get(f"{url}/supervisor-updates", headers=manager)
        assert evidence_after.json() == [retained]


async def test_concurrent_reports_cannot_both_claim_one_supervisor_update() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {setup['engineer_token']}"}
        payload = report_payload(setup["project_id"], setup["supervisor_update_id"])
        reports = [
            await client.post("/api/v1/reports", json=payload, headers=engineer) for _ in range(2)
        ]
        assert [report.status_code for report in reports] == [201, 201]
        submissions = await asyncio.gather(
            *(
                client.post(f"/api/v1/reports/{report.json()['id']}/submit", headers=engineer)
                for report in reports
            )
        )
        assert sorted(submission.status_code for submission in submissions) == [200, 409]
        accepted = next(
            submission.json() for submission in submissions if submission.status_code == 200
        )
        denied = next(
            submission.json() for submission in submissions if submission.status_code == 409
        )
        assert denied["error_code"] == "SUPERVISOR_UPDATE_ALREADY_VERIFIED"
        evidence = await client.get(
            f"/api/v1/reports/{accepted['id']}/supervisor-updates", headers=engineer
        )
        assert evidence.json()[0]["verified_report_id"] == accepted["id"]


async def test_daily_report_submit_requires_valid_supervisor_update() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], str(uuid4())),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        response = await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert response.status_code == 422


async def test_project_manager_can_approve_report_and_lock_edits() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()

        inbox_response = await client.get(
            "/api/v1/reports",
            params={"status": "submitted"},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        approve_response = await client.post(
            f"/api/v1/reports/{submitted['id']}/approve",
            json={"comments": "Target covered.", "target_covered": True},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        edit_response = await client.put(
            f"/api/v1/reports/{submitted['id']}",
            json=report_payload(setup["project_id"]),
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert inbox_response.status_code == 200
        assert inbox_response.json()["total"] >= 1
        assert approve_response.status_code == 200
        approved = approve_response.json()
        assert approved["status"] == "approved"
        assert any(item["decision"] == "approved" for item in approved["approval_history"])
        assert edit_response.status_code == 409


async def test_approval_requires_target_covered_confirmation() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()

        response = await client.post(
            f"/api/v1/reports/{submitted['id']}/approve",
            json={"comments": "Reviewed without confirmation."},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert response.status_code == 422
        assert response.json()["error_code"] == "DAILY_REPORT_TARGET_CONFIRMATION_REQUIRED"


async def test_report_approval_consumes_matching_inventory_stock() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        stock = await setup_report_consumption_stock(client, setup["project_id"], setup["op_token"])
        direct_movement = await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": stock["item_id"],
                "movement_type": "receive",
                "quantity": "1",
                "to_location_id": stock["location_id"],
                "project_id": setup["project_id"],
            },
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        assert direct_movement.status_code == 403
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        approved = await client.post(
            f"/api/v1/reports/{submitted['id']}/approve",
            json={"comments": "Target covered.", "target_covered": True},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert approved.status_code == 200, approved.text

    async with AsyncSessionLocal() as session:
        movement = await session.scalar(
            select(InventoryMovement).where(
                InventoryMovement.item_id == UUID(stock["item_id"]),
                InventoryMovement.reference_id == UUID(report["id"]),
                InventoryMovement.movement_type == "consume",
            )
        )
        assert movement is not None
        assert str(movement.quantity) == "12.000"


async def test_director_cannot_override_submitted_report() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        admin_email, admin_password = await create_user("managing_director")
        admin_token = await login_for_token(client, admin_email, admin_password)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        response = await client.post(
            f"/api/v1/reports/{submitted['id']}/override",
            json={
                "decision": "approved",
                "reason": "Emergency management approval.",
                "target_covered": True,
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        assert response.status_code == 403
        assert response.json()["error_code"] == "DAILY_REPORT_OVERRIDE_FORBIDDEN"
        unchanged = await client.get(
            f"/api/v1/reports/{submitted['id']}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["status"] == "submitted"


async def test_approved_report_can_be_downloaded_as_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        approved = (
            await client.post(
                f"/api/v1/reports/{submitted['id']}/approve",
                json={"comments": "Ready for archive.", "target_covered": True},
                headers={"Authorization": f"Bearer {setup['manager_token']}"},
            )
        ).json()
        response = await client.get(
            f"/api/v1/reports/{approved['id']}/pdf",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["cache-control"] == "no-store"
        assert response.content.startswith(b"%PDF")

        async with AsyncSessionLocal() as session:
            export = await session.scalar(
                select(ReportExport).where(ReportExport.report_id == approved["id"])
            )
        assert export is not None
        monkeypatch.setattr(
            "app.tasks.email.get_settings", lambda: Settings(report_email_recipients="")
        )
        assert await _send_report_email(str(export.id)) == "report email skipped"


async def test_report_outbox_retries_dispatch_and_reuses_the_export(monkeypatch) -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        setup = await setup_project_team(client)
        created = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        assert created.status_code == 201
        report_id = created.json()["id"]
        submitted = await client.post(
            f"/api/v1/reports/{report_id}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        assert submitted.status_code == 200
        approved = await client.post(
            f"/api/v1/reports/{report_id}/approve",
            json={"comments": "Approved for export.", "target_covered": True},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        assert approved.status_code == 200

    published_ids: list[str] = []

    def send_task(name, *, args, kwargs, task_id, **options):
        assert name == "generate_report_pdf"
        assert args[0] == report_id
        assert kwargs == {"email_after": True}
        assert options["queue"] == "report"
        published_ids.append(task_id)
        if len(published_ids) == 1:
            raise ConnectionError("Broker unavailable")

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", send_task)
    dedupe_key = f"report-pdf:{report_id}"
    async with AsyncSessionLocal() as guard:
        # Leave other tests' outbox entries alone.
        await guard.execute(
            select(TaskOutbox.id).where(TaskOutbox.dedupe_key != dedupe_key).with_for_update()
        )
        assert await _dispatch_task_outbox() == 0
        async with AsyncSessionLocal() as session:
            row = await session.scalar(
                select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key)
            )
            assert row is not None and row.status == "pending" and row.attempts == 1
        assert await _dispatch_task_outbox() == 1
        assert await _dispatch_task_outbox() == 0
    assert len(published_ids) == 2 and published_ids[0] == published_ids[1]
    first, second = await asyncio.gather(
        _generate_report_pdf(report_id, None),
        _generate_report_pdf(report_id, None),
    )
    assert first == second


async def test_report_email_updates_export_status_when_delivery_succeeds(monkeypatch) -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        approved = (
            await client.post(
                f"/api/v1/reports/{submitted['id']}/approve",
                json={"comments": "Ready for archive.", "target_covered": True},
                headers={"Authorization": f"Bearer {setup['manager_token']}"},
            )
        ).json()
        response = await client.get(
            f"/api/v1/reports/{approved['id']}/pdf",
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        export = await session.scalar(
            select(ReportExport).where(ReportExport.report_id == approved["id"])
        )
        assert export is not None

    monkeypatch.setattr(
        "app.tasks.email.get_settings",
        lambda: Settings(report_email_recipients="pm@example.com,om@example.com"),
    )

    sent_payload: dict[str, object] = {}

    def fake_send(self, *, recipients: list[str], subject: str, body: str) -> int:
        sent_payload["recipients"] = recipients
        sent_payload["subject"] = subject
        sent_payload["body"] = body
        return len(recipients)

    monkeypatch.setattr("app.tasks.email.EmailService.send", fake_send)

    assert await _send_report_email(str(export.id)) == "report email sent to 2 recipients"
    assert await _send_report_email(str(export.id)) == "report email already sent"
    assert sent_payload["recipients"] == ["pm@example.com", "om@example.com"]

    async with AsyncSessionLocal() as session:
        refreshed = await session.get(ReportExport, export.id)
        assert refreshed is not None
        assert refreshed.email_status == "sent"
        assert refreshed.emailed_at is not None


async def test_project_manager_rejects_with_required_reason() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        submitted = (
            await client.post(
                f"/api/v1/reports/{report['id']}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()

        missing_reason_response = await client.post(
            f"/api/v1/reports/{submitted['id']}/reject",
            json={"comments": ""},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )
        reject_response = await client.post(
            f"/api/v1/reports/{submitted['id']}/reject",
            json={"comments": "Missing WIR evidence."},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert missing_reason_response.status_code == 422
        assert reject_response.status_code == 200
        rejected = reject_response.json()
        assert rejected["status"] == "draft"
        assert rejected["rejection_comments"] == "Missing WIR evidence."
        assert any(item["decision"] == "rejected" for item in rejected["approval_history"])


async def test_report_revision_rejects_stale_edit_and_requires_reload_for_legacy_client() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        headers = {"Authorization": f"Bearer {setup['engineer_token']}"}
        payload = report_payload(setup["project_id"])
        created = await client.post("/api/v1/reports", json=payload, headers=headers)
        assert created.status_code == 201
        report = created.json()
        assert report["revision"] == 1
        path = f"/api/v1/reports/{report['id']}"

        legacy = await client.put(path, json=payload, headers=headers)
        assert legacy.status_code == 409
        assert legacy.json()["error_code"] == "DAILY_REPORT_REVISION_REQUIRED"

        edited = await client.put(
            path,
            json={**payload, "expected_revision": 1, "work_completed": "Updated site progress"},
            headers=headers,
        )
        assert edited.status_code == 200
        assert edited.json()["revision"] == 2

        stale = await client.put(
            path,
            json={**payload, "expected_revision": 1, "work_completed": "Older local draft"},
            headers=headers,
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "DAILY_REPORT_REVISION_CONFLICT"
        persisted = (await client.get(path, headers=headers)).json()
        assert persisted["revision"] == 2
        assert persisted["work_completed"] == "Updated site progress"
        assert persisted["manpower_entries"] == edited.json()["manpower_entries"]

        submitted = await client.post(f"{path}/submit", headers=headers)
        assert submitted.status_code == 200
        assert submitted.json()["revision"] == 3


async def test_outbox_recovers_stale_dispatch_caps_retries_and_completes_idempotently(
    monkeypatch,
) -> None:
    await skip_if_database_unavailable()
    from datetime import timedelta

    from app.tasks import outbox as outbox_module
    from app.tasks import report as report_task
    from app.utils.security import utc_now

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        created = await client.post(
            "/api/v1/reports",
            json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        assert created.status_code == 201
        report_id = created.json()["id"]
        assert (
            await client.post(
                f"/api/v1/reports/{report_id}/submit",
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/api/v1/reports/{report_id}/approve",
                json={"comments": "Approved for stale recovery.", "target_covered": True},
                headers={"Authorization": f"Bearer {setup['manager_token']}"},
            )
        ).status_code == 200

    dedupe_key = f"report-pdf:{report_id}"
    dispatched_ids: list[str] = []

    def send_task(name, *, args, kwargs, task_id, **options):
        dispatched_ids.append(task_id)

    monkeypatch.setattr("app.tasks.outbox.celery_app.send_task", send_task)

    # Simulate initial dispatch followed by worker crash before PDF export commits.
    async with AsyncSessionLocal() as guard:
        await guard.execute(
            select(TaskOutbox.id).where(TaskOutbox.dedupe_key != dedupe_key).with_for_update()
        )
        assert await _dispatch_task_outbox() == 1
        async with AsyncSessionLocal() as session:
            entry = await session.scalar(
                select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key)
            )
            assert entry is not None and entry.status == "dispatched" and entry.attempts == 1
            entry.dispatched_at = utc_now() - timedelta(minutes=10)
            await session.commit()

        # Stale dispatch must be re-dispatched with a distinct retry task_id.
        assert await _dispatch_task_outbox() == 1
        assert len(dispatched_ids) == 2 and dispatched_ids[1].endswith(":retry:2")

        # Worker executes twice concurrently with email_after=True; only one export & email.
        email_calls: list[str] = []
        monkeypatch.setattr(report_task.send_report_email, "delay", email_calls.append)
        first_export = await asyncio.to_thread(
            report_task.generate_report_pdf, report_id, None, email_after=True
        )
        assert len(email_calls) == 1
        async with AsyncSessionLocal() as session:
            export = await session.get(ReportExport, UUID(first_export))
            assert export is not None
            export.email_status = "sent"
            await session.commit()
        second_export = await asyncio.to_thread(
            report_task.generate_report_pdf, report_id, None, email_after=True
        )
        assert first_export == second_export
        assert len(email_calls) == 1

        async with AsyncSessionLocal() as session:
            completed_entry = await session.scalar(
                select(TaskOutbox).where(TaskOutbox.dedupe_key == dedupe_key)
            )
            assert completed_entry is not None and completed_entry.status == "completed"

        # Exhausted stale dispatched entry transitions cleanly to failed.
        exhausted_key = f"report-pdf:{uuid4()}"
        async with AsyncSessionLocal() as session:
            session.add(
                TaskOutbox(
                    dedupe_key=exhausted_key,
                    task_name="generate_report_pdf",
                    args_json=[str(uuid4()), None],
                    kwargs_json={"email_after": False},
                    status="dispatched",
                    attempts=outbox_module.MAX_OUTBOX_ATTEMPTS,
                    dispatched_at=utc_now() - timedelta(minutes=10),
                )
            )
            await session.commit()
        assert await _dispatch_task_outbox() == 0
        async with AsyncSessionLocal() as session:
            failed_entry = await session.scalar(
                select(TaskOutbox).where(TaskOutbox.dedupe_key == exhausted_key)
            )
            assert failed_entry is not None and failed_entry.status == "failed"
