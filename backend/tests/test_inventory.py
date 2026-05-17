from datetime import date
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.utils.security import hash_password

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
                    role_in_project="Project Manager",
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
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"]},
    )
    return str(verify_response.json()["access_token"])


async def test_inventory_stock_request_reserve_issue_and_negative_stock_block() -> None:
    await skip_if_database_unavailable()
    store, store_password = await create_user("store_keeper")
    engineer, engineer_password = await create_user("civil_engineer")
    pm, pm_password = await create_user("project_manager")
    await create_user("operation_manager")
    project = await create_project(pm, engineer)

    async with create_test_client() as client:
        store_token = await login_for_token(client, store, store_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        pm_token = await login_for_token(client, pm, pm_password)

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

        receive_response = await client.post(
            "/api/v1/inventory/movements",
            json={
                "item_id": item["id"],
                "movement_type": "receive",
                "quantity": "10",
                "to_location_id": location["id"],
                "notes": "Opening stock",
            },
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert receive_response.status_code == 201

        stock_response = await client.get(
            f"/api/v1/inventory/items/{item['id']}/stock",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert stock_response.status_code == 200
        assert stock_response.json()[0]["available_qty"] == "10.000"

        request_response = await client.post(
            "/api/v1/inventory/requests",
            json={
                "project_id": str(project.id),
                "from_location_id": location["id"],
                "notes": "Site pour",
                "lines": [{"item_id": item["id"], "quantity": "3"}],
            },
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert request_response.status_code == 201
        material_request = request_response.json()
        assert material_request["status"] == "requested"

        blocked_reserve = await client.post(
            f"/api/v1/inventory/requests/{material_request['id']}/reserve",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert blocked_reserve.status_code == 409

        approvals = await client.get(
            "/api/v1/approvals",
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert approvals.status_code == 200
        approval = next(
            item
            for item in approvals.json()["items"]
            if item["request_id"] == material_request["id"]
        )
        approved = await client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            json={"comments": "Approved for site work."},
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        assert approved.status_code == 200

        reserved = await client.post(
            f"/api/v1/inventory/requests/{material_request['id']}/reserve",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert reserved.status_code == 200
        assert reserved.json()["status"] == "reserved"
        assert reserved.json()["lines"][0]["reserved_quantity"] == "3.000"

        issued = await client.post(
            f"/api/v1/inventory/requests/{material_request['id']}/issue",
            headers={"Authorization": f"Bearer {store_token}"},
        )
        assert issued.status_code == 200
        assert issued.json()["status"] == "issued"

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

    store, store_password = await create_user("store_keeper")
    engineer, engineer_password = await create_user("civil_engineer")
    pm, pm_password = await create_user("project_manager")
    await create_user("operation_manager")
    project = await create_project(pm, engineer)

    async with create_test_client() as client:
        store_token = await login_for_token(client, store, store_password)
        engineer_token = await login_for_token(client, engineer, engineer_password)
        pm_token = await login_for_token(client, pm, pm_password)

        location_response = await client.post(
            "/api/v1/inventory/locations",
            json={
                "name": "Concurrency Warehouse",
                "code": f"CW2-{uuid4().hex[:6]}",
                "location_type": "warehouse",
                "address": "Industrial Area",
            },
            headers={"Authorization": f"Bearer {store_token}"},
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
            headers={"Authorization": f"Bearer {store_token}"},
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
            headers={"Authorization": f"Bearer {store_token}"},
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
            headers={"Authorization": f"Bearer {store_token}"},
        )

        request_response = await client.post(
            "/api/v1/inventory/requests",
            json={
                "project_id": str(project.id),
                "from_location_id": location["id"],
                "notes": "Site pour",
                "lines": [{"item_id": item["id"], "quantity": "5"}],
            },
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        material_request = request_response.json()

        approvals = await client.get(
            "/api/v1/approvals",
            headers={"Authorization": f"Bearer {pm_token}"},
        )
        approval = next(
            item
            for item in approvals.json()["items"]
            if item["request_id"] == material_request["id"]
        )
        await client.post(
            f"/api/v1/approvals/{approval['id']}/approve",
            json={"comments": "Approved for site work."},
            headers={"Authorization": f"Bearer {pm_token}"},
        )

        async def make_reserve_request():
            async with create_test_client() as new_client:
                return await new_client.post(
                    f"/api/v1/inventory/requests/{material_request['id']}/reserve",
                    headers={"Authorization": f"Bearer {store_token}"},
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
                    headers={"Authorization": f"Bearer {store_token}"},
                )

        issue_responses = await asyncio.gather(*[make_issue_request() for _ in range(5)])
        issue_success = sum(1 for r in issue_responses if r.status_code == 200)
        assert issue_success == 1, f"Expected exactly 1 successful issuance, got {issue_success}."
