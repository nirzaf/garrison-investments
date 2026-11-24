from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.users import UserUpdateRequest
from app.services.user_service import UserService
from app.utils.permissions import ROLE_MANAGING_DIRECTOR, permissions_for_role
from app.utils.security import utc_now
from tests.concurrency_helpers import race, status_counts
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
                employee_code=f"TEST-{uuid4().hex[:8]}",
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


async def test_managing_director_can_create_filter_and_deactivate_users() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("managing_director")

    async with create_test_client() as client:
        token = await login_for_token(client, admin_email, admin_password)
        created_response = await client.post(
            "/api/v1/users",
            json={
                "email": f"managed-{uuid4().hex}@example.com",
                "full_name": "Managed Engineer",
                "role": "quantity_surveyor",
                "employee_code": f"ENG-{uuid4().hex[:8]}",
                "phone": "+97455550111",
                "designation": "Quantity Surveyor",
                "temporary_password": "Managed123!",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert created_response.status_code == 201
        created_user = created_response.json()
        assert created_user["role"] == "quantity_surveyor"

        list_response = await client.get(
            "/api/v1/users",
            params={"active": "true", "role": "quantity_surveyor"},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert list_response.status_code == 200
        assert any(item["id"] == created_user["id"] for item in list_response.json()["items"])

        deactivate_response = await client.delete(
            f"/api/v1/users/{created_user['id']}",
            headers={"Authorization": f"Bearer {token}"},
            params={"expected_updated_at": created_user["updated_at"]},
        )

        assert deactivate_response.status_code == 200
        assert deactivate_response.json()["is_active"] is False


async def test_group_project_manager_can_read_users_but_cannot_manage_users() -> None:
    await skip_if_database_unavailable()
    op_email, op_password = await create_user("group_project_manager")

    async with create_test_client() as client:
        token = await login_for_token(client, op_email, op_password)
        list_response = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert list_response.status_code == 200

        create_response = await client.post(
            "/api/v1/users",
            json={
                "email": f"blocked-{uuid4().hex}@example.com",
                "full_name": "Blocked User",
                "role": "administrative_executive",
                "employee_code": f"ACC-{uuid4().hex[:8]}",
                "phone": "+97455550222",
                "designation": "Administrative Executive",
                "temporary_password": "Blocked123!",
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert create_response.status_code == 403


async def test_user_state_preconditions_permissions_and_revocation() -> None:
    await skip_if_database_unavailable()
    admin_credentials = await create_user("managing_director")
    engineer_credentials = await create_user("quantity_surveyor")
    manager_credentials = await create_user("group_project_manager")

    async with create_test_client() as client, create_test_client() as subject:
        admin_token = await login_for_token(client, *admin_credentials)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        admin_id = (await client.get("/api/v1/auth/me", headers=admin_headers)).json()["id"]
        engineer_token = await login_for_token(subject, *engineer_credentials)
        engineer_headers = {"Authorization": f"Bearer {engineer_token}"}
        engineer_id = (await subject.get("/api/v1/auth/me", headers=engineer_headers)).json()["id"]
        challenge = await subject.post(
            "/api/v1/auth/login",
            json={"email": engineer_credentials[0], "password": engineer_credentials[1]},
        )
        assert challenge.status_code == 200
        engineer_url = f"/api/v1/users/{engineer_id}"
        manager_token = await login_for_token(client, *manager_credentials)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}
        self_read = await client.get(engineer_url, headers=engineer_headers)
        assert self_read.status_code == 200
        assert (
            not {
                "password_hash",
                "access_revision",
                "refresh_token",
            }
            & self_read.json().keys()
        )
        engineer = (await client.get(engineer_url, headers=manager_headers)).json()
        assert engineer["permissions"] == permissions_for_role("quantity_surveyor")
        assert not {"password_hash", "access_revision", "refresh_token"} & engineer.keys()
        exact_email = await client.get(
            "/api/v1/users",
            headers=manager_headers,
            params={"email": engineer_credentials[0].upper()},
        )
        assert exact_email.status_code == 200
        assert [row["id"] for row in exact_email.json()["items"]] == [engineer_id]
        assert exact_email.json()["total"] == 1
        roles = (await client.get("/api/v1/users/roles", headers=manager_headers)).json()["items"]
        assert {item["role"] for item in roles} == {
            "managing_director",
            "operations_director",
            "group_project_manager",
            "mep_project_manager",
            "quantity_surveyor",
            "senior_site_supervisor",
            "site_supervisor",
            "hr_manager",
            "hr_executive_reader",
            "administrative_executive",
        }
        hr_executive = next(item for item in roles if item["role"] == "hr_executive_reader")
        assert set(hr_executive["permissions"]) == {
            "users:read",
            "dashboard:scoped",
            "documents:view",
        }
        assert hr_executive["assignable"] is False
        update = {
            "role": "administrative_executive",
            "expected_updated_at": engineer["updated_at"],
        }
        assert (
            await client.patch(engineer_url, headers=manager_headers, json=update)
        ).status_code == 403
        changed = await client.patch(engineer_url, headers=admin_headers, json=update)
        assert changed.status_code == 200, changed.text
        assert changed.json()["role"] == "administrative_executive"
        assert changed.json()["designation"] == engineer["designation"]
        assert (await subject.get("/api/v1/auth/me", headers=engineer_headers)).status_code == 401
        assert (await subject.post("/api/v1/auth/refresh")).status_code == 401
        otp = challenge.json()
        used_challenge = await subject.post(
            "/api/v1/auth/verify-otp",
            json={"challenge_id": otp["challenge_id"], "otp": otp["dev_otp"]},
        )
        assert used_challenge.status_code == 401

        for stale_response in (
            await client.patch(engineer_url, headers=admin_headers, json=update),
            await client.delete(
                engineer_url,
                headers=admin_headers,
                params={"expected_updated_at": engineer["updated_at"]},
            ),
            await client.post(
                f"{engineer_url}/reset-password",
                headers=admin_headers,
                json={"new_password": "Reset456!", "expected_updated_at": engineer["updated_at"]},
            ),
        ):
            assert stale_response.status_code == 409
            assert stale_response.json()["error_code"] == "USER_STATE_CONFLICT"

        login = await login_for_token(subject, *engineer_credentials)
        current = (await client.get(engineer_url, headers=admin_headers)).json()
        off = await client.delete(
            engineer_url,
            headers=admin_headers,
            params={"expected_updated_at": current["updated_at"]},
        )
        assert off.status_code == 200
        on = await client.patch(
            engineer_url,
            headers=admin_headers,
            json={
                "is_active": True,
                "designation": None,
                "expected_updated_at": off.json()["updated_at"],
            },
        )
        assert on.status_code == 200
        assert on.json()["designation"] is None
        assert (
            await subject.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login}"})
        ).status_code == 401
        self_state = await client.get(f"/api/v1/users/{admin_id}", headers=admin_headers)
        self_deactivate = await client.delete(
            f"/api/v1/users/{admin_id}",
            headers=admin_headers,
            params={"expected_updated_at": self_state.json()["updated_at"]},
        )
        assert self_deactivate.json()["error_code"] == "SELF_DEACTIVATION_BLOCKED"
        self_reset = await client.post(
            f"/api/v1/users/{admin_id}/reset-password",
            headers=admin_headers,
            json={"new_password": "Reset456!"},
        )
        assert self_reset.json()["error_code"] == "SELF_PASSWORD_RESET_BLOCKED"

    async with AsyncSessionLocal() as session:
        events = await session.scalars(
            select(ActivityLog).where(
                ActivityLog.entity_id == UUID(engineer_id), ActivityLog.action == "users.updated"
            )
        )
        assert [event.user_id for event in events] == [UUID(admin_id)] * 3


async def test_concurrent_director_demotions_leave_one_active_director() -> None:
    await skip_if_database_unavailable()
    # Keep the test population exact even when the integration database contains
    # administrators from earlier tests. The schema contains synthetic rows only.
    schema = f"test_role_change_{uuid4().hex}"
    async with engine.begin() as connection:
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        for table in ("users", "auth_refresh_tokens", "auth_otp_challenges", "activity_log"):
            await connection.execute(
                text(f"CREATE TABLE {schema}.{table} (LIKE public.{table} INCLUDING ALL)")
            )
    isolated = create_async_engine(
        get_settings().database_url,
        connect_args={"server_settings": {"search_path": f"{schema},public"}},
    )
    sessions = async_sessionmaker(isolated, expire_on_commit=False)
    try:
        async with sessions() as session:
            usable = [
                User(
                    email=f"{i}@example.com",
                    full_name=f"Director {i}",
                    role=ROLE_MANAGING_DIRECTOR if i == 0 else "operations_director",
                    password_hash=hash_fixture_password("Start123!"),
                )
                for i in range(2)
            ]
            locked = User(
                email="locked@example.com",
                full_name="Locked director",
                role="managing_director",
                password_hash=hash_fixture_password("Start123!"),
                locked_until=utc_now() + timedelta(hours=1),
            )
            no_password = User(
                email="empty@example.com",
                full_name="No password",
                role="operations_director",
            )
            session.add_all([*usable, locked, no_password])
            await session.commit()
            user_ids = [user.id for user in usable]

        async def demote(actor_id: UUID, target_id: UUID) -> int:
            async with sessions() as session:
                actor = await UserRepository(session).get_by_id(actor_id)
                target = await UserRepository(session).get_by_id(target_id)
                assert actor is not None
                assert target is not None
                await UserService(session).update_user(
                    target_id,
                    UserUpdateRequest(
                        role="administrative_executive", expected_updated_at=target.updated_at
                    ),
                    actor,
                )
                return 200

        outcomes = await race(demote(user_ids[0], user_ids[1]), demote(user_ids[1], user_ids[0]))
        assert status_counts(outcomes) == {200: 1, 403: 1}
        async with sessions() as session:
            active_directors = await session.scalars(
                select(User.id).where(
                    User.role.in_({ROLE_MANAGING_DIRECTOR, "operations_director"}),
                    User.is_active.is_(True),
                    User.deleted_at.is_(None),
                    User.locked_until.is_(None),
                    User.password_hash.is_not(None),
                )
            )
            assert len(list(active_directors)) == 1
    finally:
        await isolated.dispose()
        async with engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
