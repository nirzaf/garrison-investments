import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.inventory import InventoryItem, StorageLocation
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
        stored_payload = {
            **request_payload["requirements"],
            "from_location_id": location["id"],
            "notes": "Saved for another session",
            "lines": request_payload["lines"],
        }
        save_url = f"/api/v1/inventory/requests/drafts/{draft['id']}"
        update_payload = {"expected_revision": draft["revision"], "payload": stored_payload}
        foreign = await client.put(save_url, json=update_payload, headers=store_headers)
        assert foreign.status_code == 404, foreign.text
        saved = await client.put(save_url, json=update_payload, headers=owner_headers)
        assert saved.status_code == 200, saved.text
        stale = await client.put(save_url, json=update_payload, headers=owner_headers)
        assert stale.status_code == 409, stale.text
        reloaded = await client.get(
            "/api/v1/inventory/requests",
            params={"request_id": draft["id"]},
            headers=owner_headers,
        )
        assert reloaded.json()[0]["draft_payload"]["notes"] == stored_payload["notes"]
        assert reloaded.json()[0]["submission_revision"] is None
        draft = saved.json()
        fields = {
            "entity_type": "material_request",
            "entity_id": draft["id"],
            "classification": "operational",
        }
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

            async def run_reminders():
                async with AsyncSessionLocal() as worker_session:
                    return await ApprovalService(worker_session).send_reminders_and_escalations()

            await asyncio.gather(run_reminders(), run_reminders())
            await session.refresh(overdue)
            approvals = ApprovalService(session)
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

        from app.models.approval import Approval
        from app.models.inventory import MaterialRequest
        from app.models.notification import Notification
        from app.services.approval_service import ApprovalService

        async with AsyncSessionLocal() as session:
            returned_approval = await session.get(Approval, UUID(manager["id"]))
            assert returned_approval is not None
            returned_notice = await session.scalar(
                select(Notification).where(
                    Notification.reference_id == returned_approval.id,
                    Notification.user_id == requester.id,
                    Notification.title == "Approval returned",
                )
            )
            assert returned_notice is not None
            assert await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            returned_notice_id = returned_notice.id
            original_decider = returned_approval.decided_by
            original_decided_at = returned_approval.decided_at
            returned_approval.decided_by = requester.id
            await session.commit()
            assert not await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            returned_approval.decided_by = original_decider
            returned_approval.decided_at = None
            await session.commit()
            assert not await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            returned_approval.decided_at = original_decided_at
            await session.commit()
            assert await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            request_row = await session.get(MaterialRequest, UUID(request_id))
            assert request_row is not None
            request_row.status = "cancelled"
            await session.commit()
            assert not await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            request_row.status = "returned"
            recipient = await session.get(User, requester.id)
            assert recipient is not None
            recipient.is_active = False
            await session.commit()
            assert not await ApprovalService(session).can_deliver_scheduled_email(returned_notice)
            recipient.is_active = True
            await session.commit()
            assert await ApprovalService(session).can_deliver_scheduled_email(returned_notice)

        correction = await client.post(
            "/api/v1/inventory/requests/drafts",
            json={
                "project_id": str(project.id),
                "correction_target_id": request_id,
                "correction_expected_revision": material_request["revision"] + 2,
            },
            headers=owner_headers,
        )
        assert correction.status_code == 201, correction.text
        correction_draft = correction.json()
        correction_upload = await client.post(
            "/api/v1/photos/upload",
            data={
                "entity_type": "material_request",
                "entity_id": correction_draft["id"],
                "classification": "operational",
            },
            files={"files": ("correction.jpg", jpeg_bytes(), "image/jpeg")},
            headers=owner_headers,
        )
        assert correction_upload.status_code == 201, correction_upload.text
        corrected_file_id = correction_upload.json()[0]["id"]
        corrected = await client.post(
            f"/api/v1/inventory/requests/drafts/{correction_draft['id']}/submit-correction",
            json={
                **request_payload,
                "notes": "Confirmed delivery",
                "expected_revision": correction_draft["revision"],
            },
            headers=owner_headers,
        )
        assert corrected.status_code == 200, corrected.text
        assert corrected.json()["submission_revision"] == 2
        assert corrected.json()["status"] == "pending_engineer"
        async with AsyncSessionLocal() as session:
            stale_return_notice = await session.get(Notification, returned_notice_id)
            assert stale_return_notice is not None
            assert not await ApprovalService(session).can_deliver_scheduled_email(
                stale_return_notice
            )
        evidence = await client.get(
            f"/api/v1/inventory/requests/{request_id}/submissions", headers=owner_headers
        )
        assert [
            row["requirements"]["evidence_file_ids"] for row in evidence.json()["submissions"]
        ] == [[corrected_file_id], [file_id]]
        locked = await client.delete(f"/api/v1/photos/{corrected_file_id}", headers=owner_headers)
        assert locked.status_code == 409, locked.text
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
                data={
                    "entity_type": "inventory_registration",
                    "entity_id": row["id"],
                    "classification": "operational",
                },
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
                        InventoryMovement.reference_type == "inventory_registration",
                        InventoryMovement.project_id == project.id,
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

        asset_url = f"{path}/{approved['id']}/correction-assets"
        eligible = await client.get(asset_url, headers=owner, params={"search": "REG-", "limit": 1})
        assert eligible.status_code == 200, eligible.text
        assert eligible.json()["total"] == 1
        assert eligible.json()["items"][0]["location_name"] == location.name
        assert eligible.json()["items"][0]["condition"] == "new"
        forbidden = await client.get(asset_url, headers=reviewer)
        assert forbidden.status_code == 403, forbidden.text
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
        eligible = await client.get(f"{path}/{changed['id']}/correction-assets", headers=owner)
        assert eligible.status_code == 200, eligible.text
        assert eligible.json()["total"] == 2
        selected = eligible.json()["items"][0]["id"]
        reduction_payload = {
            **approved_correction,
            "expected_submission_revision": 4,
            "reason": "Review count after discovering a duplicate receipt",
            "serial_number": None,
            "quantity": "1",
            "remove_asset_ids": [selected],
        }
        rejected_draft = await client.post(
            f"{path}/{changed['id']}/correction", json=reduction_payload, headers=owner
        )
        assert rejected_draft.status_code == 201, rejected_draft.text
        rejected_id = rejected_draft.json()["id"]
        await upload_and_submit(rejected_draft.json(), 5)
        rejected = await client.post(
            f"{path}/{rejected_id}/decision",
            json={
                "decision": "rejected",
                "expected_submission_revision": 5,
                "comments": "Recount.",
            },
            headers=reviewer,
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["movement_id"] is None
        selection = await client.get(f"{path}/{rejected_id}/correction-assets", headers=owner)
        assert selection.status_code == 200, selection.text
        assert Decimal(selection.json()["effective_quantity"]) == 2
        reduction = await client.post(
            f"{path}/{rejected_id}/correction",
            json={**reduction_payload, "expected_submission_revision": 5},
            headers=owner,
        )
        assert reduction.status_code == 201, reduction.text
        await upload_and_submit(reduction.json(), 6)
        reduced = await client.post(
            f"{path}/{reduction.json()['id']}/decision",
            json={"decision": "approved", "expected_submission_revision": 6},
            headers=reviewer,
        )
        assert reduced.status_code == 200, reduced.text
        assert reduced.json()["confirmed_item_id"] == approved["confirmed_item_id"]

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
        ) == Decimal("1")
        assert (
            await session.scalar(
                select(func.count(InventoryAsset.id)).where(InventoryAsset.item_id == item_id)
            )
            == 2
        )

        removed = await session.get(InventoryAsset, UUID(selected))
        assert removed is not None and removed.deleted_at is not None

        movement = await session.scalar(
            select(InventoryMovement).where(InventoryMovement.reference_id == UUID(changed["id"]))
        )
        assert movement is not None
        assert movement.movement_type == "adjustment"
        assert movement.quantity == Decimal("1")


@pytest.mark.parametrize(
    "op_threshold,md_threshold,cost,stages,scenario",
    [
        (None, None, "10000", (1, 2), ""),
        ("1000", None, "999.99", (1, 2), ""),
        ("1000", None, "1000", (1, 2, 3), ""),
        (None, "5000", "5000", (1, 2, 4), ""),
        ("1000", "5000", "5000", (1, 2, 3, 4), ""),
        ("0", None, "0", (1, 2, 3), ""),
        ("1000", None, "1000", (1, 2, 3), "frozen"),
        ("1000", None, "1000", (1, 2, 3), "correct"),
        ("1000", None, "1000", (1, 2, 3), "unavailable"),
        ("1000", None, "1000", (1, 2, 3), "return"),
        ("1000", None, "1000", (1, 2, 3), "reject"),
        (None, None, None, (1, 2), "unknown-default"),
        ("1000", None, None, (1, 2, 3), "unknown-operations"),
        (None, "5000", None, (1, 2, 4), "unknown-md"),
        ("1000", "5000", None, (1, 2, 3, 4), "unknown"),
    ],
    ids=[
        "default",
        "below",
        "operations-boundary",
        "md-only",
        "all",
        "zero-threshold-known-zero",
        "frozen",
        "correct",
        "unavailable",
        "return",
        "reject",
        "unknown-default",
        "unknown-operations",
        "unknown-md",
        "unknown-valuation",
    ],
)
async def test_material_director_stage_sequence(
    monkeypatch, op_threshold, md_threshold, cost, stages, scenario
):
    await skip_if_database_unavailable()
    policy = Settings(
        material_operations_approval_threshold=op_threshold,
        material_md_approval_threshold=md_threshold,
    )
    monkeypatch.setattr("app.services.approval_service.get_settings", lambda: policy)
    operations, ops_password = await create_user("operations_director")
    director, md_password = await create_user("managing_director")
    engineer, engineer_password = await create_user("mep_project_manager")
    manager, manager_password = await create_user("group_project_manager")
    supervisor, supervisor_password = await create_user("site_supervisor")
    project = await create_project(manager, engineer)
    async with AsyncSessionLocal.begin() as session:
        session.add_all(
            [
                ProjectMember(project_id=project.id, user_id=user.id)
                for user in (supervisor, operations, director)
            ]
        )
    if scenario == "unavailable":
        from app.services.approval_service import ApprovalService

        async def no_director(*_args, **_kwargs):
            return None

        monkeypatch.setattr(ApprovalService, "_first_active_scoped_approver", no_director)
    async with create_test_client() as client:
        ops = await login_for_token(client, operations, ops_password)
        headers = {"Authorization": f"Bearer {ops}"}
        location = await client.post(
            "/api/v1/inventory/locations",
            json={
                "name": "Stage test warehouse",
                "code": uuid4().hex,
                "location_type": "warehouse",
            },
            headers=headers,
        )
        assert location.status_code == 201, location.text
        item_id = uuid4()
        async with AsyncSessionLocal.begin() as session:
            session.add(
                InventoryItem(
                    id=item_id,
                    name="Stage test item",
                    unit="Nos",
                    item_type="consumable",
                    category="Civil",
                    unit_cost=Decimal(cost) if cost is not None else None,
                )
            )
            known_item_id = uuid4()
            if cost is None:
                session.add(
                    InventoryItem(
                        id=known_item_id,
                        name="Known subtotal item",
                        unit="Nos",
                        item_type="consumable",
                        category="Civil",
                        unit_cost=Decimal("1.25"),
                    )
                )
        owner = await login_for_token(client, supervisor, supervisor_password)
        payload = {
            "project_id": str(project.id),
            "from_location_id": location.json()["id"],
            "requirements": material_requirements(),
            "lines": [
                {"item_id": str(item_id), "quantity": "1"},
                *(
                    [{"item_id": str(known_item_id), "quantity": "1"}]
                    if cost is None
                    else []
                ),
            ],
        }
        owner_headers = {"Authorization": f"Bearer {owner}"}
        created = await client.post(
            "/api/v1/inventory/requests",
            json=payload,
            headers=owner_headers,
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        if scenario.startswith("unknown"):
            history = await client.get(
                f"/api/v1/inventory/requests/{request_id}/submissions", headers=headers
            )
            assert history.status_code == 200, history.text
            frozen = history.json()["submissions"][0]["requirements"]
            assert frozen["valuation_complete"] is False
            assert frozen["valuation_status"] == "incomplete"
            assert frozen["approval_stages"] == list(stages)
            current = await client.get(
                "/api/v1/inventory/requests", headers=headers, params={"request_id": request_id}
            )
            assert current.json()[0]["total_estimated_cost"] is None
            assert current.json()[0]["valuation_status"] == "incomplete"
            owner_history = await client.get(
                f"/api/v1/inventory/requests/{request_id}/submissions",
                headers=owner_headers,
            )
            assert owner_history.status_code == 200
            assert owner_history.json()["submissions"][0]["requirements"][
                "valuation_status"
            ] is None
            from app.models.inventory import MaterialRequest

            async with AsyncSessionLocal() as session:
                stored_request = await session.get(MaterialRequest, UUID(request_id))
                assert stored_request is not None
                assert stored_request.total_estimated_cost == Decimal("1.25")
        if scenario == "frozen":
            policy = Settings(
                material_operations_approval_threshold=None, material_md_approval_threshold=None
            )
        tokens = {
            1: await login_for_token(client, engineer, engineer_password),
            2: await login_for_token(client, manager, manager_password),
            3: ops,
            4: await login_for_token(client, director, md_password),
        }
        statuses = {
            1: "pending_engineer",
            2: "pending_gpm",
            3: "pending_operations",
            4: "pending_md",
        }
        for stage in stages:
            current = await client.get(
                "/api/v1/inventory/requests", headers=headers, params={"request_id": request_id}
            )
            assert current.json()[0]["status"] == statuses[stage]
            if stage == 2 and scenario == "unavailable":
                pending = await material_inbox_item(client, tokens[2], request_id)
                rejected = await client.post(
                    f"/api/v1/approvals/{pending['id']}/approve",
                    json={"expected_submission_revision": 1},
                    headers={"Authorization": f"Bearer {tokens[2]}"},
                )
                assert rejected.status_code == 409, rejected.text
                assert rejected.json()["error_code"] == "APPROVER_NOT_CONFIGURED"
                remaining = await material_inbox_item(client, tokens[2], request_id)
                assert remaining["id"] == pending["id"]
                return
            if stage > 2:
                blocked = await client.post(
                    f"/api/v1/inventory/requests/{request_id}/reserve", headers=headers
                )
                assert blocked.status_code == 409, blocked.text
                assert blocked.json()["error_code"] == "MATERIAL_APPROVALS_REQUIRED"
                dashboard = await client.get(
                    "/api/v1/dashboard/summary",
                    headers={"Authorization": f"Bearer {tokens[2]}"},
                )
                assert dashboard.status_code == 200, dashboard.text
                assert dashboard.json()["site_operations"]["material_requests_awaiting_review"] == 1
                outbox = await client.get(
                    "/api/v1/approvals",
                    params={"box": "outbox"},
                    headers={"Authorization": f"Bearer {owner}"},
                )
                masked = next(row for row in outbox.json()["items"] if row["step_order"] == stage)
                assert masked["amount"] is None and masked["currency"] is None
                assigned = await material_inbox_item(client, tokens[stage], request_id)
                if scenario.startswith("unknown"):
                    assert assigned["amount"] is None and assigned["currency"] is None
                else:
                    assert Decimal(assigned["amount"]) == Decimal(cost)
                forbidden = await client.post(
                    f"/api/v1/approvals/{assigned['id']}/approve",
                    json={"expected_submission_revision": 1},
                    headers={"Authorization": f"Bearer {tokens[2]}"},
                )
                assert forbidden.status_code in (403, 409)
            if stage == 3 and scenario in {"return", "reject"}:
                acted = await client.post(
                    f"/api/v1/approvals/{assigned['id']}/{scenario}",
                    json={"expected_submission_revision": 1, "comments": "Check delivery date."},
                    headers=headers,
                )
                assert acted.status_code == 200, acted.text
                decided = await client.get(
                    "/api/v1/inventory/requests", headers=headers, params={"request_id": request_id}
                )
                assert (
                    decided.json()[0]["status"]
                    == {"return": "returned", "reject": "rejected"}[scenario]
                )
                return
            await approve_material_stage(client, tokens[stage], request_id, stage)
        final = await client.get(
            "/api/v1/inventory/requests", headers=headers, params={"request_id": request_id}
        )
        assert final.json()[0]["status"] == "approved"
        if scenario.startswith("unknown"):
            from sqlalchemy import select

            from app.models.approval import Approval

            async with AsyncSessionLocal() as session:
                decisions = await session.scalars(
                    select(Approval).where(
                        Approval.request_type == "material_request",
                        Approval.request_id == UUID(request_id),
                        Approval.submission_revision == 1,
                    )
                )
                rows = list(decisions)
                assert [row.step_order for row in rows] == list(stages)
                assert all(row.amount is None for row in rows)
        if stages == (1, 2, 3, 4):
            from sqlalchemy import select

            from app.models.approval import Approval

            async with AsyncSessionLocal.begin() as session:
                final_approval = await session.scalar(
                    select(Approval).where(
                        Approval.request_id == UUID(request_id), Approval.step_order == 4
                    )
                )
                assert final_approval is not None
                final_approval.decided_by = manager.id
            for operation in ("reserve", "issue"):
                denied = await client.post(
                    f"/api/v1/inventory/requests/{request_id}/{operation}",
                    headers=headers,
                )
                assert denied.status_code == 409, denied.text
                assert denied.json()["error_code"] == "MATERIAL_APPROVALS_REQUIRED"
        if scenario == "correct":
            corrected = await client.post(
                f"/api/v1/inventory/requests/{request_id}/resubmit",
                json={
                    **payload,
                    "expected_revision": final.json()[0]["revision"],
                    "reason": "Change delivery requirements",
                },
                headers=owner_headers,
            )
            assert corrected.status_code == 200, corrected.text
            assert corrected.json()["status"] == "pending_engineer"
            assert corrected.json()["submission_revision"] == 2
            await approve_material_stage(client, tokens[1], request_id, 1, revision=2)
