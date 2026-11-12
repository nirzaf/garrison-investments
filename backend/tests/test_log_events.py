from __future__ import annotations

import asyncio
import io
import json
import socket
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
import uvicorn

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.activity_log import ActivityLog
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
    action = f"test.stream.{uuid4().hex}"
    timestamp = utc_now()
    event_count = 205

    async with AsyncSessionLocal() as session:
        session.add_all(
            ActivityLog(action=action, created_at=timestamp) for _ in range(event_count)
        )
        await session.commit()

    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        admin_token = await login_for_token(client, admin_email, admin_password)
        async with (
            asyncio.timeout(10),
            client.stream(
                "GET",
                "/api/v1/log-events/stream",
                params={
                    "action": action,
                    "created_from": (utc_now() - timedelta(minutes=5)).isoformat(),
                },
                headers={"Authorization": f"Bearer {admin_token}", "X-Log-CLI-Session": "cli-tail"},
            ) as response,
        ):
            assert response.status_code == 200
            ids: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line.removeprefix("data: "))
                    assert payload["action"] == action
                    ids.append(payload["id"])
                if len(ids) == event_count:
                    break
            assert len(ids) == event_count
            assert ids == sorted(set(ids))


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

        audit = AuditService(session)
        audit.settings = audit.settings.model_copy(update={"log_purge_enabled": True})
        assert await audit.purge_logs(archive_retention_days=365) == 0

        log = logs[0]
        log.retention_until = utc_now() - timedelta(seconds=1)
        await session.flush()
        preview = await audit.preview_purge(archive_retention_days=365)
        assert [row[0] for row in preview] == [log.id]
        assert await AuditService(session).purge_logs(archive_retention_days=365) == 0

        log.retention_until = None
        await session.flush()
        assert await audit.purge_logs(archive_retention_days=365) == 0
        log.retention_until = utc_now() - timedelta(seconds=1)
        await session.flush()
        assert await audit.purge_logs(archive_retention_days=365) == 1
        await session.commit()


@asynccontextmanager
async def serve_test_api():
    # A real socket lets clients disconnect from SSE and keeps database I/O on the test loop.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        host, port = listener.getsockname()
        server = uvicorn.Server(uvicorn.Config(create_app(), lifespan="off", log_config=None))
        server_task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    await asyncio.sleep(0.01)
            yield f"http://{host}:{port}"
        finally:
            server.should_exit = True
            await asyncio.wait_for(server_task, timeout=5)


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

    async with serve_test_api() as base_url:
        login_output = io.StringIO()
        assert (
            await asyncio.to_thread(
                log_cli.run,
                [
                    "--base-url",
                    base_url,
                    "login",
                    "--email",
                    admin_email,
                    "--password",
                    admin_password,
                ],
                stdout=login_output,
            )
            == 0
        )
        token = login_output.getvalue().split("access_token=", 1)[1].splitlines()[0].strip()

        search_output = io.StringIO()
        assert (
            await asyncio.to_thread(
                log_cli.run,
                [
                    "--base-url",
                    base_url,
                    "--token",
                    token,
                    "search",
                    "--action",
                    "users.created",
                ],
                stdout=search_output,
            )
            == 0
        )
        assert "users.created" in search_output.getvalue()
