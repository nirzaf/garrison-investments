from __future__ import annotations

import io
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.audit_service import AuditService
from app.utils.security import hash_password, utc_now
from scripts import log_cli

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
    email = f"logs-{role}-{uuid4().hex}@example.com"
    async with AsyncSessionLocal() as session:
        await UserRepository(session).add(
            User(
                email=email,
                full_name=f"{role} Logs User",
                role=role,
                employee_code=f"LOG-{uuid4().hex[:8]}",
                phone="+97455550333",
                designation=role.replace("_", " ").title(),
                password_hash=hash_password(password),
                must_change_password=False,
            )
        )
        await session.commit()
    return email, password


def create_async_client() -> httpx.AsyncClient:
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


async def test_admin_can_search_log_events_and_non_admin_cannot() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("admin")
    engineer_email, engineer_password = await create_user("civil_engineer")

    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_email(admin_email)
        assert admin is not None
        await AuditService(session).record(
            action="projects.updated",
            event_type="state_change",
            severity="INFO",
            user_id=admin.id,
            entity_type="projects",
            endpoint="/api/v1/projects",
            comments="Project status changed",
            context_payload={"phase": "qa"},
            old_values={"status": "draft"},
            new_values={"status": "active"},
        )
        await session.commit()

    async with create_async_client() as client:
        admin_token = await login_for_token(client, admin_email, admin_password)
        engineer_token = await login_for_token(client, engineer_email, engineer_password)

        response = await client.get(
            "/api/v1/log-events",
            params={"event_type": "state_change", "search": "qa", "endpoint": "/api/v1/projects"},
            headers={"Authorization": f"Bearer {admin_token}", "X-Log-CLI-Session": "cli-search"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert any(
            item["event_type"] == "state_change"
            and item["endpoint"] == "/api/v1/projects"
            and item["context_payload"]["phase"] == "qa"
            for item in payload["items"]
        )

        blocked = await client.get(
            "/api/v1/log-events",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked.status_code == 403


async def test_log_event_stream_returns_matching_events() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("admin")

    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_email(admin_email)
        assert admin is not None
        await AuditService(session).record(
            action="maintenance.logs_retention",
            event_type="system_event",
            severity="INFO",
            user_id=admin.id,
            comments="Retention completed",
            source_service="backend-api",
        )
        await session.commit()

    async with create_async_client() as client:
        admin_token = await login_for_token(client, admin_email, admin_password)
        async with client.stream(
            "GET",
            "/api/v1/log-events/stream",
            params={
                "action": "maintenance.logs_retention",
                "created_from": (utc_now() - timedelta(minutes=5)).isoformat(),
            },
            headers={"Authorization": f"Bearer {admin_token}", "X-Log-CLI-Session": "cli-tail"},
        ) as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = httpx.Response(200, text=line.removeprefix("data: ")).json()
                    assert payload["action"] == "maintenance.logs_retention"
                    break
            else:
                pytest.fail("stream did not yield a log event")


async def test_log_retention_archives_then_purges_old_logs() -> None:
    await skip_if_database_unavailable()
    async with AsyncSessionLocal() as session:
        await AuditService(session).record(
            action="system.old_log",
            event_type="system_event",
            severity="INFO",
            comments="Old hot log",
        )
        await session.commit()
        logs, _ = await AuditService(session).list_logs(action="system.old_log")
        assert logs
        log = logs[0]
        log.created_at = utc_now() - timedelta(days=400)
        await session.commit()

        archived = await AuditService(session).archive_logs(hot_retention_days=30)
        assert archived >= 1
        await session.commit()

        logs, _ = await AuditService(session).list_logs(
            action="system.old_log",
            storage_tier="archive",
        )
        assert logs
        logs[0].archived_at = utc_now() - timedelta(days=400)
        await session.commit()

        purged = await AuditService(session).purge_logs(archive_retention_days=365)
        assert purged >= 1
        await session.commit()


class CliTestClientAdapter:
    def __init__(self, *, base_url: str, token: str | None = None):
        self.client = TestClient(create_app(), base_url=base_url.rstrip("/"))
        if token:
            self.client.headers.update({"Authorization": f"Bearer {token}"})

    def __enter__(self):
        self.client.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.client.__exit__(exc_type, exc, tb)

    def post(self, *args, **kwargs):
        return self.client.post(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)

    def stream(self, *args, **kwargs):
        return self.client.stream(*args, **kwargs)


async def test_log_cli_login_and_search() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("admin")

    async with AsyncSessionLocal() as session:
        admin = await UserRepository(session).get_by_email(admin_email)
        assert admin is not None
        await AuditService(session).record(
            action="users.created",
            event_type="user_action",
            severity="INFO",
            user_id=admin.id,
            comments="CLI visible entry",
        )
        await session.commit()

    login_output = io.StringIO()
    assert (
        log_cli.run(
            [
                "--base-url",
                "http://testserver",
                "login",
                "--email",
                admin_email,
                "--password",
                admin_password,
            ],
            client_factory=CliTestClientAdapter,
            stdout=login_output,
        )
        == 0
    )
    token = login_output.getvalue().split("access_token=", 1)[1].splitlines()[0].strip()

    search_output = io.StringIO()
    assert (
        log_cli.run(
            [
                "--base-url",
                "http://testserver",
                "--token",
                token,
                "search",
                "--action",
                "users.created",
            ],
            client_factory=CliTestClientAdapter,
            stdout=search_output,
        )
        == 0
    )
    assert "users.created" in search_output.getvalue()
