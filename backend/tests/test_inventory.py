import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.inventory import StorageLocation
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import utc_now
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


async def create_user(role: str, password: str = "Start123!") -> tuple[User, str]:
    user = User(
        email=f"inventory-{role}-{uuid4().hex}@example.com",
        full_name=f"{role} Inventory User",
        role=role,
        employee_code=f"INV-{uuid4().hex[:8]}",
        phone="+97455550555",
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
            name=f"Inventory Test {uuid4().hex[:6]}",
            code=f"INV-{uuid4().hex[:6]}",
            location="Doha",
            description="Inventory test project",
            scope_of_work="Inventory test scope",
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
                    project_id=project.id,
                    user_id=pm.id,
                    role_in_project="Group Project Manager",
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


def material_requirements() -> dict[str, str]:
    return {
        "required_date": date.today().isoformat(),
        "urgency": "routine",
        "purpose": "Site concrete pour",
        "specification": "Specified grade of cement",
    }


async def material_inbox_item(client: httpx.AsyncClient, token: str, request_id: str) -> dict:
    response = await client.get("/api/v1/approvals", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["request_id"] == request_id)


async def approve_material_stage(
    client: httpx.AsyncClient,
    token: str,
    request_id: str,
    step: int,
    revision: int = 1,
) -> None:
    approval = await material_inbox_item(client, token, request_id)
    assert (approval["step_order"], approval["submission_revision"]) == (step, revision)
    response = await client.post(
        f"/api/v1/approvals/{approval['id']}/approve",
        json={"expected_submission_revision": revision, "comments": "Reviewed on site."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text


async def test_inventory_stock_request_reserve_issue_and_negative_stock_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    policy = Settings(app_env="test", business_currency="LKR")
    monkeypatch.setattr("app.services.approval_service.get_settings", lambda: policy)
    store, store_password = await create_user("operations_director")
    engineer, engineer_password = await create_user("mep_project_manager")
    pm, pm_password = await create_user("group_project_manager")
    requester, requester_password = await create_user("site_supervisor")
    processor, processor_password = await create_user("administrative_executive")
    project = await create_project(pm, engineer)
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                ProjectMember(project_id=project.id, user_id=requester.id),
                ProjectMember(project_id=project.id, user_id=processor.id),
            ]
        )
        await session.commit()

    async with create_test_client() as client:
        store_token = await login_for_token(client, store, store_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        pm_token = await login_for_token(client, pm, pm_password)
        requester_token = await login_for_token(client, requester, requester_password)
        processor_token = await login_for_token(client, processor, processor_password)

        location_response = await client.post(
            "/api/v1/inventory/locations",
            json={
                "name": "Central Warehouse",
                "code": f"CW-{uuid4().hex[:6]}",
                "location_type": "warehouse",
                "address": "Industrial Area",
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert location_response.status_code == 201
        location = location_response.json()

        supplier_response = await client.post(
            "/api/v1/suppliers",
            json={
                "name": "Qatar Cement Supplier",
                "category": "Civil",
                "rating": "A",
                "payment_terms": "30 days",
                "contact_person": "Supplier Contact",
                "phone": "+97455550666",
                "email": f"supplier-{uuid4().hex}@example.com",
                "address": "Industrial Area",
                "tax_registration_number": f"TAX-{uuid4().hex[:8]}",
                "tds_certificate_number": "TDS-001",
                "tds_expiry_date": "2027-05-16",
                "compliance_status": "compliant",
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert supplier_response.status_code == 201
        supplier = supplier_response.json()

        item_response = await client.post(
            "/api/v1/inventory/items",
            json={
                "name": "Cement Bag",
                "item_code": f"CEM-{uuid4().hex[:6]}",
                "category": "Civil",
                "item_type": "consumable",
                "unit": "Nos",
                "minimum_stock": "5",
                "reorder_level": "5",
                "unit_cost": "12.50",
                "supplier_id": supplier["id"],
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert item_response.status_code == 201
        item = item_response.json()

        movement_payload = {
            "item_id": item["id"],
            "movement_type": "receive",
            "quantity": "10",
            "to_location_id": location["id"],
            "notes": "Opening stock",
        }
        movement_headers = {
            "Authorization": f"Bearer {store_token}",
            "Idempotency-Key": f"receipt-{uuid4()}",
        }
        receive_response, replay = await asyncio.gather(
            *(
                client.post(
                    "/api/v1/inventory/movements", json=movement_payload, headers=movement_headers
                )
                for _ in range(2)
            )
        )
        assert receive_response.status_code == replay.status_code == 201
        assert receive_response.json() == replay.json()
        reused_key = await client.post(
            "/api/v1/inventory/movements",
            json={**movement_payload, "quantity": "11"},
            headers=movement_headers,
        )
        assert reused_key.status_code == 409
        assert reused_key.json()["error_code"] == "MOVEMENT_REPLAY_CONFLICT"

        stock_response = await client.get(
            f"/api/v1/inventory/items/{item['id']}/stock",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert stock_response.status_code == 200
        assert stock_response.json()[0]["available_qty"] == "10.000"

        async with AsyncSessionLocal() as session:
            unavailable_destinations = [
                StorageLocation(
                    name="Inactive store",
                    code=f"OFF-{uuid4().hex[:6]}",
                    location_type="warehouse",
                    is_active=False,
                ),
                StorageLocation(
                    name="Archived store",
                    code=f"DEL-{uuid4().hex[:6]}",
                    location_type="warehouse",
                    deleted_at=utc_now(),
                ),
            ]
            session.add_all(unavailable_destinations)
            await session.flush()
            unavailable_ids = [str(row.id) for row in unavailable_destinations]
            await session.commit()

        store_headers = {"Authorization": f"Bearer {store_token}"}
        receipt = {"item_id": item["id"], "movement_type": "receive", "quantity": "1.000"}
        for destination in [*unavailable_ids, str(uuid4())]:
            refused = await client.post(
                "/api/v1/inventory/movements",
                headers=store_headers,
                json={**receipt, "to_location_id": destination},
            )
            assert refused.status_code == 404, refused.text
            assert "Eligible receipt destination" in refused.json()["detail"]

        too_small = await client.post(
            "/api/v1/inventory/movements",
            headers=store_headers,
            json={**receipt, "to_location_id": location["id"], "quantity": "0.0001"},
        )
        assert too_small.status_code == 422
        after_refusal = await client.get(
            f"/api/v1/inventory/items/{item['id']}/stock", headers=store_headers
        )
        assert after_refusal.json() == stock_response.json()
        item_movements = await client.get(
            "/api/v1/inventory/movements", headers=store_headers, params={"item_id": item["id"]}
        )
        assert [row["id"] for row in item_movements.json()] == [receive_response.json()["id"]]

        request_payload = {
            "project_id": str(project.id),
            "from_location_id": location["id"],
            "notes": "Site pour",
            "requirements": material_requirements(),
            "lines": [{"item_id": item["id"], "quantity": "3"}],
        }
        for token in (engineer_token, pm_token):
            forbidden = await client.post(
                "/api/v1/inventory/requests",
                json=request_payload,
                headers={"Authorization": f"Bearer {token}"},
            )
            assert forbidden.status_code == 403
        from tests.test_photos import jpeg_bytes

        owner_headers = {"Authorization": f"Bearer {requester_token}"}
        drafted = await client.post(
            "/api/v1/inventory/requests/drafts",
            json={"project_id": str(project.id)},
            headers=owner_headers,
        )
        assert drafted.status_code == 201, drafted.text
        draft = drafted.json()
        fields = {"entity_type": "material_request", "entity_id": draft["id"]}
        upload = await client.post(
            "/api/v1/photos/upload",
            data=fields,
            files={"files": ("request.jpg", jpeg_bytes(), "image/jpeg")},
            headers=owner_headers,
        )
        assert upload.status_code == 201, upload.text
        file_id = upload.json()[0]["id"]
        denied = await client.get(
            f"/api/v1/photos/{file_id}/download",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert denied.status_code == 404
        request_response = await client.post(
            f"/api/v1/inventory/requests/{draft['id']}/resubmit",
            json={**request_payload, "expected_revision": draft["revision"]},
            headers=owner_headers,
        )
        assert request_response.status_code == 200, request_response.text
        locked = await client.delete(f"/api/v1/photos/{file_id}", headers=owner_headers)
        assert locked.status_code == 409, locked.text
        evidence = await client.get(
            f"/api/v1/inventory/requests/{draft['id']}/submissions", headers=owner_headers
        )
        assert evidence.json()["submissions"][0]["requirements"]["evidence_file_ids"] == [file_id]
        material_request = request_response.json()
        assert material_request["status"] == "pending_engineer"
        assert material_request["submission_revision"] == 1
        request_id = material_request["id"]
        direct_movement = await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": item["id"],
                "movement_type": "issue",
                "quantity": "1",
                "from_location_id": location["id"],
                "project_id": str(project.id),
                "reference_type": "material_request",
                "reference_id": request_id,
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert direct_movement.status_code == 409, direct_movement.text
        assert direct_movement.json()["error_code"] == "MATERIAL_REQUEST_WORKFLOW_REQUIRED"
        for token in (store_token, processor_token):
            blocked_reserve = await client.post(
                f"/api/v1/inventory/requests/{request_id}/reserve",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert blocked_reserve.status_code == 409
            assert blocked_reserve.json()["error_code"] == "MATERIAL_APPROVALS_REQUIRED"

        technical = await material_inbox_item(client, engineer_token, request_id)
        assert technical["amount"] is None and technical["currency"] is None
        from sqlalchemy import select

        from app.models.approval import Approval
        from app.models.notification import Notification
        from app.services.approval_service import MATERIAL_OVERDUE_TITLE, ApprovalService

        async with AsyncSessionLocal() as session:
            overdue = await session.get(Approval, UUID(technical["id"]))
            assert overdue is not None
            overdue.due_at = utc_now() - timedelta(days=3)
            await session.commit()
            approvals = ApprovalService(session)
            await approvals.send_reminders_and_escalations()
            await approvals.send_reminders_and_escalations()
            assert overdue.status == "pending"
            assert overdue.approver_id == engineer.id
            assert overdue.escalation_user_id is None
            notice = (
                await session.scalars(
                    select(Notification).where(
                        Notification.reference_id == overdue.id,
                        Notification.user_id == store.id,
                        Notification.title == MATERIAL_OVERDUE_TITLE,
                    )
                )
            ).one()
            assert await approvals.can_deliver_scheduled_email(notice)
            notice_id = notice.id

        read_only = await material_inbox_item(client, store_token, request_id)
        assert read_only["id"] == technical["id"]
        for token in (requester_token, pm_token, store_token):
            bypass = await client.post(
                f"/api/v1/approvals/{technical['id']}/approve",
                json={"expected_submission_revision": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert bypass.status_code == 403, bypass.text
        stale = await client.post(
            f"/api/v1/approvals/{technical['id']}/approve",
            json={"expected_submission_revision": 2},
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert stale.status_code == 409
        assert stale.json()["error_code"] == "SUBMISSION_REVISION_CONFLICT"
        await approve_material_stage(client, engineer_token, request_id, 1)
        async with AsyncSessionLocal() as session:
            queued = await session.get(Notification, notice_id)
            assert queued is not None
            assert not await ApprovalService(session).can_deliver_scheduled_email(queued)

        blocked_reserve = await client.post(
            f"/api/v1/inventory/requests/{request_id}/reserve",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert blocked_reserve.status_code == 409
        manager = await material_inbox_item(client, pm_token, request_id)
        assert manager["currency"] == "LKR"
        returned = await client.post(
            f"/api/v1/approvals/{manager['id']}/return",
            json={"comments": "Confirm the delivery date.", "expected_submission_revision": 1},
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert returned.status_code == 200, returned.text

        corrected = await client.post(
            f"/api/v1/inventory/requests/{request_id}/resubmit",
            json={
                **request_payload,
                "notes": "Confirmed delivery",
                "expected_revision": material_request["revision"] + 2,
            },
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["submission_revision"] == 2
        assert corrected.json()["status"] == "pending_engineer"
        retired = await client.post(
            f"/api/v1/approvals/{manager['id']}/approve",
            json={"expected_submission_revision": 1},
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert retired.status_code == 409
        await approve_material_stage(client, engineer_token, request_id, 1, 2)
        await approve_material_stage(client, pm_token, request_id, 2, 2)

        history = await client.get(
            f"/api/v1/inventory/requests/{request_id}/submissions",
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert history.status_code == 200, history.text
        assert [row["requirements"]["notes"] for row in history.json()["submissions"]] == [
            "Confirmed delivery",
            "Site pour",
        ]
        assert [row["status"] for row in history.json()["decisions"]] == [
            "approved",
            "approved",
            "approved",
            "returned",
        ]

        reserved = await client.post(
            f"/api/v1/inventory/requests/{material_request['id']}/reserve",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert reserved.status_code == 200
        assert reserved.json()["status"] == "reserved"
        assert reserved.json()["submission_revision"] == 2
        assert reserved.json()["lines"][0]["reserved_quantity"] == "3.000"

        issued = await client.post(
            f"/api/v1/inventory/requests/{material_request['id']}/issue",
            headers={"Authorization": f"Bearer {processor_token}"},
        )
        assert issued.status_code == 200, issued.text
        assert issued.json()["status"] == "issued"
        assert issued.json()["submission_revision"] == 2
        assert issued.json()["revision"] == reserved.json()["revision"] + 1

        for path, filters, total in (
            ("items", {"search": item["item_code"]}, 1),
            ("movements", {"item_id": item["id"]}, 3),
            ("requests", {"request_id": material_request["id"]}, 1),
        ):
            headers = {"Authorization": f"Bearer {store_token}"}
            page = await client.get(
                f"/api/v1/inventory/{path}", params={**filters, "limit": 1}, headers=headers
            )
            assert page.status_code == 200
            assert page.headers["X-Total-Count"] == str(total)
            assert len(page.json()) == 1
            empty = await client.get(
                f"/api/v1/inventory/{path}",
                params={**filters, "limit": 1, "offset": total},
                headers=headers,
            )
            assert empty.status_code == 200
            assert empty.json() == []
            assert empty.headers["X-Total-Count"] == str(total)

        negative = await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": item["id"],
                "movement_type": "issue",
                "quantity": "100",
                "from_location_id": location["id"],
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert negative.status_code == 409

        low_stock = await client.get(
            "/api/v1/inventory/low-stock",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert low_stock.status_code == 200


async def test_reserve_request_concurrency() -> None:
    await skip_if_database_unavailable()
    import asyncio

    ops_director, ops_director_password = await create_user("operations_director")
    qs, engineer_password = await create_user("mep_project_manager")
    group_pm, pm_password = await create_user("group_project_manager")
    requester, requester_password = await create_user("managing_director")
    project = await create_project(group_pm, qs)

    async with create_test_client() as client:
        ops_director_token = await login_for_token(client, ops_director, ops_director_password)
        requester_token = await login_for_token(client, requester, requester_password)
        engineer_token = await login_for_token(client, qs, engineer_password)
        pm_token = await login_for_token(client, group_pm, pm_password)

        location_response = await client.post(
            "/api/v1/inventory/locations",
            json={
                "name": "Concurrency Warehouse",
                "code": f"CW2-{uuid4().hex[:6]}",
                "location_type": "warehouse",
                "address": "Industrial Area",
            },
            headers={"Authorization": f"Bearer {ops_director_token}"},
        )
        location = location_response.json()

        supplier_response = await client.post(
            "/api/v1/suppliers",
            json={
                "name": "Concurrency Supplier",
                "category": "Civil",
                "rating": "A",
                "payment_terms": "30 days",
                "contact_person": "Supplier Contact",
                "phone": "+97455550666",
                "email": f"supp-con-{uuid4().hex}@example.com",
                "address": "Industrial Area",
                "tax_registration_number": f"TAX2-{uuid4().hex[:8]}",
                "tds_certificate_number": "TDS-002",
                "tds_expiry_date": "2027-05-16",
                "compliance_status": "compliant",
            },
            headers={"Authorization": f"Bearer {ops_director_token}"},
        )
        supplier = supplier_response.json()

        item_response = await client.post(
            "/api/v1/inventory/items",
            json={
                "name": "Concurrency Item",
                "item_code": f"CITEM-{uuid4().hex[:6]}",
                "category": "Civil",
                "item_type": "consumable",
                "unit": "Nos",
                "minimum_stock": "5",
                "reorder_level": "5",
                "unit_cost": "12.50",
                "supplier_id": supplier["id"],
            },
            headers={"Authorization": f"Bearer {ops_director_token}"},
        )
        item = item_response.json()

        await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": item["id"],
                "movement_type": "receive",
                "quantity": "5",
                "to_location_id": location["id"],
                "notes": "Opening stock",
            },
            headers={"Authorization": f"Bearer {ops_director_token}"},
        )

        request_response = await client.post(
            "/api/v1/inventory/requests",
            json={
                "project_id": str(project.id),
                "from_location_id": location["id"],
                "notes": "Site pour",
                "requirements": material_requirements(),
                "lines": [{"item_id": item["id"], "quantity": "5"}],
            },
            headers={"Authorization": f"Bearer {requester_token}"},
        )
        assert request_response.status_code == 201, request_response.text
        material_request = request_response.json()

        request_id = material_request["id"]
        technical = await material_inbox_item(client, engineer_token, request_id)
        decisions = await asyncio.gather(
            *[
                client.post(
                    f"/api/v1/approvals/{technical['id']}/approve",
                    json={"expected_submission_revision": 1},
                    headers={"Authorization": f"Bearer {engineer_token}"},
                )
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in decisions) == [200, 409]
        await approve_material_stage(client, pm_token, request_id, 2)

        async def make_reserve_request():
            async with create_test_client() as new_client:
                return await new_client.post(
                    f"/api/v1/inventory/requests/{material_request['id']}/reserve",
                    headers={"Authorization": f"Bearer {ops_director_token}"},
                )

        reserve_responses = await asyncio.gather(*[make_reserve_request() for _ in range(5)])

        success_count = sum(1 for r in reserve_responses if r.status_code == 200)
        assert success_count == 1, (
            f"Expected exactly 1 successful reservation, got {success_count}."
        )

        async def make_issue_request():
            async with create_test_client() as new_client:
                return await new_client.post(
                    f"/api/v1/inventory/requests/{material_request['id']}/issue",
                    headers={"Authorization": f"Bearer {ops_director_token}"},
                )

        issue_responses = await asyncio.gather(*[make_issue_request() for _ in range(5)])
        issue_success = sum(1 for r in issue_responses if r.status_code == 200)
        assert issue_success == 1, f"Expected exactly 1 successful issuance, got {issue_success}."


async def test_request_project_lookup_and_write_share_active_role_and_membership_scope() -> None:
    await skip_if_database_unavailable()
    roles = (
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
    users_by_role = {role: await create_user(role) for role in roles}
    pm, engineer = users_by_role["group_project_manager"][0], users_by_role["quantity_surveyor"][0]
    assigned = await create_project(pm, engineer)
    other_site_supervisor, _ = await create_user("site_supervisor")
    other = await create_project(users_by_role["managing_director"][0], other_site_supervisor)
    inactive = await create_project(pm, engineer)
    prefix = f"REQ-{uuid4().hex[:8]}"
    async with AsyncSessionLocal() as session:
        for project, suffix in ((assigned, "A"), (other, "B"), (inactive, "C")):
            record = await session.get(Project, project.id)
            assert record is not None
            record.code = f"{prefix}-{suffix}"
            if project.id == inactive.id:
                record.status = "completed"
        await session.commit()

    company_creators = {"managing_director", "operations_director"}
    inventory_viewers = {
        "managing_director",
        "operations_director",
        "group_project_manager",
        "mep_project_manager",
        "quantity_surveyor",
        "senior_site_supervisor",
        "site_supervisor",
        "administrative_executive",
    }
    async with AsyncSessionLocal() as session:
        session.add_all(
            ProjectMember(
                project_id=assigned.id,
                user_id=users_by_role[role][0].id,
                role_in_project="inventory viewer",
            )
            for role in inventory_viewers
            - company_creators
            - {
                "group_project_manager",
                "quantity_surveyor",
            }
        )
        await session.commit()
    async with create_test_client() as client:
        for role, (user, password) in users_by_role.items():
            headers = {"Authorization": f"Bearer {await login_for_token(client, user, password)}"}
            lookup = "/api/v1/inventory/request-projects"
            first = await client.get(lookup, params={"search": prefix, "limit": 1}, headers=headers)
            eligible = (
                {str(assigned.id), str(other.id)}
                if role in company_creators
                else {str(assigned.id)}
            )
            if role not in inventory_viewers:
                assert first.status_code == 403
                eligible = set()
            else:
                assert first.status_code == 200
                assert first.json()["total"] == len(eligible), (
                    f"unexpected project scope for {role}: {first.json()}"
                )
                options = first.json()["items"]
                if len(eligible) > 1:
                    second = await client.get(
                        lookup,
                        params={"search": prefix, "limit": 1, "offset": 1},
                        headers=headers,
                    )
                    assert second.status_code == 200
                    options.extend(second.json()["items"])
                assert {item["id"] for item in options} == eligible
                assert all(set(item) == {"id", "code", "name"} for item in options)

            # An unknown source isolates the project guard before a fixture write can occur.
            for project_id in (assigned.id, other.id, inactive.id, uuid4()):
                result = await client.post(
                    "/api/v1/inventory/requests",
                    headers=headers,
                    json={
                        "project_id": str(project_id),
                        "from_location_id": str(uuid4()),
                        "requirements": material_requirements(),
                        "lines": [{"item_id": str(uuid4()), "quantity": "1.000"}],
                    },
                )
                if role not in company_creators | {"site_supervisor", "senior_site_supervisor"}:
                    assert result.status_code == 403
                else:
                    assert result.status_code == 404
                    expected = (
                        "Eligible request source location"
                        if str(project_id) in eligible
                        else "Eligible request project"
                    )
                    assert expected in result.json()["detail"]


async def test_registration_requires_evidence_and_confirms_one_receipt() -> None:
    await skip_if_database_unavailable()
    from sqlalchemy import func, select

    from app.models.inventory import InventoryAsset, InventoryLocationStock, InventoryMovement
    from tests.test_photos import jpeg_bytes

    pm, _ = await create_user("group_project_manager")
    engineer, engineer_password = await create_user("mep_project_manager")
    outsider, outsider_password = await create_user("mep_project_manager")
    supervisor, supervisor_password = await create_user("senior_site_supervisor")
    director, director_password = await create_user("operations_director")
    surveyor, surveyor_password = await create_user("quantity_surveyor")
    project = await create_project(pm, engineer)
    async with AsyncSessionLocal() as session:
        location = StorageLocation(
            project_id=project.id,
            name="Registration stockroom",
            code=f"REG-{uuid4().hex[:6]}",
            location_type="project_site",
        )
        session.add_all(
            [
                location,
                ProjectMember(project_id=project.id, user_id=supervisor.id),
                ProjectMember(project_id=project.id, user_id=surveyor.id),
            ]
        )
        await session.commit()

    draft = {
        "project_id": str(project.id),
        "location_id": str(location.id),
        "name": "Site equipment",
        "description": "Inspected equipment",
        "category": "equipment",
        "unit": "Nos",
        "quantity": "1",
        "condition": "new",
        "received_date": date.today().isoformat(),
        "serial_number": "REG-TEST-1",
    }
    path = "/api/v1/inventory/registrations"
    async with create_test_client() as client:
        owner_token = await login_for_token(client, supervisor, supervisor_password)
        owner = {"Authorization": f"Bearer {owner_token}"}
        reviewer_token = await login_for_token(client, engineer, engineer_password)
        reviewer = {"Authorization": f"Bearer {reviewer_token}"}
        denied = {
            "Authorization": f"Bearer {await login_for_token(client, outsider, outsider_password)}"
        }
        operations = {
            "Authorization": f"Bearer {await login_for_token(client, director, director_password)}"
        }
        qs = {
            "Authorization": f"Bearer {await login_for_token(client, surveyor, surveyor_password)}"
        }
        created = await client.post(path, json=draft, headers=owner)
        assert created.status_code == 201, created.text
        first = f"{path}/{created.json()['id']}"
        stage1 = {"expected_submission_revision": 1}
        filters = {"registration_id": created.json()["id"]}
        assert (await client.get(path, headers=qs, params=filters)).json()["items"] == []
        missing = await client.post(f"{first}/submit", json=stage1, headers=owner)
        assert missing.status_code == 422
        assert missing.json()["error_code"] == "REGISTRATION_PHOTO_REQUIRED"

        async def upload_and_submit(row: dict, revision: int) -> None:
            uploaded = await client.post(
                "/api/v1/photos/upload",
                data={"entity_type": "inventory_registration", "entity_id": row["id"]},
                files={"files": ("equipment.jpg", jpeg_bytes(), "image/jpeg")},
                headers=owner,
            )
            assert uploaded.status_code == 201, uploaded.text
            submitted = await client.post(
                f"{path}/{row['id']}/submit",
                json={"expected_submission_revision": revision},
                headers=owner,
            )
            assert submitted.status_code == 200, submitted.text
            assert submitted.json()["movement_id"] is None
            assert submitted.json()["evidence_ids"] == [uploaded.json()[0]["id"]]
            hidden = await client.get(
                f"/api/v1/photos/{uploaded.json()[0]['id']}/download", headers=denied
            )
            assert hidden.status_code == 404
            locked = await client.delete(
                f"/api/v1/photos/{uploaded.json()[0]['id']}", headers=owner
            )
            assert locked.status_code == 409

        await upload_and_submit(created.json(), 1)
        scoped = await client.get(path, headers=qs, params=filters)
        assert scoped.status_code == 200, scoped.text
        assert [row["id"] for row in scoped.json()["items"]] == [created.json()["id"]]
        assert (await client.get(path, headers=denied, params=filters)).json()["items"] == []
        for headers, expected in ((owner, 403), (denied, 404), (operations, 403), (qs, 403)):
            forbidden = await client.post(
                f"{first}/decision", json={**stage1, "decision": "approved"}, headers=headers
            )
            assert forbidden.status_code == expected, forbidden.text
        returned = await client.post(
            f"{first}/decision",
            json={**stage1, "decision": "returned", "comments": "Check model identification."},
            headers=reviewer,
        )
        assert returned.status_code == 200, returned.text
        assert returned.json()["movement_id"] is None

        corrected = await client.post(
            f"{first}/correction",
            json={**draft, **stage1, "model_number": "Model A"},
            headers=owner,
        )
        assert corrected.status_code == 201, corrected.text
        correction = corrected.json()
        assert correction["previous_id"] == created.json()["id"]
        assert correction["submission_revision"] == 2
        await upload_and_submit(correction, 2)

        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count(InventoryMovement.id)).where(
                        InventoryMovement.reference_type == "inventory_registration"
                    )
                )
                == 0
            )

        decisions = await asyncio.gather(
            *[
                client.post(
                    f"{path}/{correction['id']}/decision",
                    json={"decision": "approved", "expected_submission_revision": 2},
                    headers=reviewer,
                )
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in decisions) == [200, 409], [
            response.text for response in decisions
        ]
        approved = next(response.json() for response in decisions if response.status_code == 200)
        assert approved["confirmed_item_id"] and approved["movement_id"]
        history = await client.get(f"{path}/{correction['id']}/history", headers=owner)
        assert [entry["status"] for entry in history.json()] == ["approved", "returned"]

        approved_correction = {
            **draft,
            "expected_submission_revision": 2,
            "reason": "Correct the model label",
            "model_number": "Model B",
        }
        successor = await client.post(
            f"{path}/{approved['id']}/correction", json=approved_correction, headers=owner
        )
        assert successor.status_code == 201, successor.text
        repeated = await client.post(
            f"{path}/{approved['id']}/correction", json=approved_correction, headers=owner
        )
        assert repeated.status_code == 409, repeated.text
        await upload_and_submit(successor.json(), 3)
        adjusted = await client.post(
            f"{path}/{successor.json()['id']}/decision",
            json={"decision": "approved", "expected_submission_revision": 3},
            headers=reviewer,
        )
        assert adjusted.status_code == 200, adjusted.text
        assert adjusted.json()["confirmed_item_id"] == approved["confirmed_item_id"]
        assert adjusted.json()["movement_id"] is None
        quantity_correction = await client.post(
            f"{path}/{adjusted.json()['id']}/correction",
            json={
                **approved_correction,
                "expected_submission_revision": 3,
                "reason": "One additional identical tool was received",
                "serial_number": None,
                "quantity": "2",
            },
            headers=owner,
        )
        assert quantity_correction.status_code == 201, quantity_correction.text
        changed = quantity_correction.json()
        await upload_and_submit(changed, 4)
        attempts = await asyncio.gather(
            *[
                client.post(
                    f"{path}/{changed['id']}/decision",
                    json={"decision": "approved", "expected_submission_revision": 4},
                    headers=reviewer,
                )
                for _ in range(2)
            ]
        )
        assert sorted(response.status_code for response in attempts) == [200, 409]

    async with AsyncSessionLocal() as session:
        assert (
            await session.scalar(
                select(func.count(InventoryMovement.id)).where(
                    InventoryMovement.reference_type == "inventory_registration",
                    InventoryMovement.reference_id == UUID(correction["id"]),
                )
            )
            == 1
        )
        item_id = UUID(approved["confirmed_item_id"])
        assert await session.scalar(
            select(InventoryLocationStock.on_hand_qty).where(
                InventoryLocationStock.item_id == item_id,
                InventoryLocationStock.location_id == location.id,
            )
        ) == Decimal("2")
        assert (
            await session.scalar(
                select(func.count(InventoryAsset.id)).where(InventoryAsset.item_id == item_id)
            )
            == 2
        )

        movement = await session.scalar(
            select(InventoryMovement).where(InventoryMovement.reference_id == UUID(changed["id"]))
        )
        assert movement is not None
        assert movement.movement_type == "adjustment"
        assert movement.quantity == Decimal("1")
