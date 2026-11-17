from __future__ import annotations

import asyncio
import io
import json
import socket
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import uvicorn
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import DBAPIError

from app.database import AsyncSessionLocal, check_database, engine
from app.main import create_app
from app.models.activity_log import ActivityLog
from app.models.auth import AuthSession
from app.models.business_log_stream import BusinessLogStream
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services import business_log_stream
from app.services.audit_retention_policy import AuditRetentionPolicyError
from app.services.audit_service import AuditService
from app.utils.security import create_access_token, decode_access_token, utc_now
from scripts import log_cli
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
                password_hash=hash_fixture_password(password),
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
    admin_email, admin_password = await create_user("managing_director")
    engineer_email, engineer_password = await create_user("quantity_surveyor")

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
            storage_tier="archive",
        )
        await session.commit()

    async with create_async_client() as client:
        admin_token = await login_for_token(client, admin_email, admin_password)
        engineer_token = await login_for_token(client, engineer_email, engineer_password)

        response = await client.get(
            "/api/v1/log-events",
            params={
                "event_type": "state_change",
                "search": "qa",
                "endpoint": "/api/v1/projects",
                "storage_tier": "archive",
            },
            headers={"Authorization": f"Bearer {admin_token}", "X-Log-CLI-Session": "cli-search"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] >= 1
        assert any(
            item["event_type"] == "state_change"
            and item["endpoint"] == "/api/v1/projects"
            and item["context_payload"]["phase"] == "qa"
            and item["storage_tier"] == "archive"
            for item in payload["items"]
        )

        blocked = await client.get(
            "/api/v1/log-events",
            headers={"Authorization": f"Bearer {engineer_token}"},
        )
        assert blocked.status_code == 403


async def test_log_event_stream_returns_matching_events() -> None:
    await skip_if_database_unavailable()
    admin_email, admin_password = await create_user("managing_director")
    action = f"test.stream.{uuid4().hex}"
    timestamp = utc_now()
    event_count = 205

    async with AsyncSessionLocal() as session:
        session.add_all(
            ActivityLog(action=action, created_at=timestamp) for _ in range(event_count)
        )
        await session.commit()

    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        unauthorized = await client.get("/api/v1/log-events/stream")
        assert unauthorized.status_code == 401
        engineer_email, engineer_password = await create_user("quantity_surveyor")
        engineer_token = await login_for_token(client, engineer_email, engineer_password)
        forbidden = await client.get(
            "/api/v1/log-events/stream", headers={"Authorization": f"Bearer {engineer_token}"}
        )
        assert forbidden.status_code == 403
        admin_token = await login_for_token(client, admin_email, admin_password)
        query_only = await client.get(
            "/api/v1/log-events/stream", params={"access_token": "fixture"}
        )
        assert query_only.status_code == 401
        token_without_session, _ = create_access_token(
            UUID(decode_access_token(admin_token)["sub"]), "managing_director",
        )
        assert (await client.get(
            "/api/v1/log-events/stream",
            headers={"Authorization": f"Bearer {token_without_session}"},
        )).status_code == 401
        headers = {"Authorization": f"Bearer {admin_token}", "X-Log-CLI-Session": "cli-tail"}
        async with (
            asyncio.timeout(10),
            client.stream(
                "GET",
                "/api/v1/log-events/stream",
                params={
                    "action": action,
                    "created_from": (utc_now() - timedelta(minutes=5)).isoformat(),
                },
                headers=headers,
            ) as response,
        ):
            assert response.status_code == 200
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["cache-control"] == "no-store"
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
        async with (
            asyncio.timeout(5),
            client.stream(
                "GET", "/api/v1/log-events/stream", params={"action": action},
                headers={**headers, "Last-Event-ID": ids[99]},
            ) as resumed,
        ):
            assert resumed.status_code == 200
            lines = resumed.aiter_lines()
            assert await anext(lines) == f"id: {ids[100]}"


async def test_log_stream_limits_and_releases_slots_then_stops_after_idle_revocation() -> None:
    await skip_if_database_unavailable()
    email, password = await create_user("managing_director")
    path = "/api/v1/log-events/stream"
    params = {"action": f"test.revocation.{uuid4().hex}"}
    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        token = await login_for_token(client, email, password)
        claims = decode_access_token(token)
        user_id, auth_id = UUID(claims["sub"]), UUID(claims["sid"])
        headers = {"Authorization": f"Bearer {token}"}
        async with asyncio.timeout(10), AsyncExitStack() as stack:
            admitted = await asyncio.gather(*(
                stack.enter_async_context(
                    client.stream("GET", path, params=params, headers=headers)
                )
                for _ in range(3)
            ))
            assert sorted(item.status_code for item in admitted) == [200, 200, 429]
            first, second = [item for item in admitted if item.status_code == 200]
            assert await anext(first.aiter_lines()) == ": keep-alive"
            await first.aclose()
            while True:
                async with AsyncSessionLocal() as db:
                    closed = await db.scalar(select(func.count()).select_from(
                        BusinessLogStream
                    ).where(
                        BusinessLogStream.user_id == user_id,
                        BusinessLogStream.closed_at.is_not(None),
                    ))
                if closed == 1:
                    break
                await asyncio.sleep(0.05)
            third = await stack.enter_async_context(
                client.stream("GET", path, params=params, headers=headers)
            )
            assert third.status_code == 200
            async with AsyncSessionLocal() as db:
                await db.execute(update(AuthSession).where(AuthSession.id == auth_id).values(
                    revoked_at=utc_now()
                ))
                db.add(ActivityLog(action=params["action"], comments="after-revocation-fixture"))
                await db.commit()
            for stream in (second, third):
                lines = [line async for line in stream.aiter_lines()]
                assert ": closed authorization_ended" in lines
                assert not any(line.startswith("data: ") for line in lines)


async def test_log_stream_rechecks_role_after_query_before_sending_a_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    email, password = await create_user("managing_director")
    action = f"test.role-loss.{uuid4().hex}"
    projected, proceed = asyncio.Event(), asyncio.Event()
    original = AuditService.list_logs

    async def observe_query(self, **kwargs):
        result = await original(self, **kwargs)
        if kwargs.get("action") == action and kwargs.get("ascending"):
            projected.set()
            await proceed.wait()
        return result

    monkeypatch.setattr(AuditService, "list_logs", observe_query)
    async with AsyncSessionLocal() as db:
        db.add(ActivityLog(action=action, comments="preauthorization-fixture"))
        await db.commit()
    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        token = await login_for_token(client, email, password)
        async with asyncio.timeout(6), client.stream(
            "GET", "/api/v1/log-events/stream", params={"action": action},
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            assert response.status_code == 200
            try:
                await projected.wait()
                async with AsyncSessionLocal() as db:
                    await db.execute(update(User).where(User.email == email).values(
                        role="quantity_surveyor"
                    ))
                    await db.commit()
            finally:
                proceed.set()
            lines = [line async for line in response.aiter_lines()]
            assert ": closed authorization_ended" in lines
            assert not any(line.startswith("data: ") for line in lines)


async def test_log_stream_stops_for_an_expired_bearer_even_while_idle() -> None:
    await skip_if_database_unavailable()
    email, password = await create_user("managing_director")
    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        token = await login_for_token(client, email, password)
        claims = decode_access_token(token)
        short, _ = create_access_token(
            UUID(claims["sub"]), "managing_director", access_revision=claims["access_revision"],
            auth_session_id=UUID(claims["sid"]),
            session_expires_at=utc_now() + timedelta(seconds=2),
        )
        async with asyncio.timeout(7), client.stream(
            "GET", "/api/v1/log-events/stream", params={"action": f"unused.{uuid4().hex}"},
            headers={"Authorization": f"Bearer {short}"},
        ) as response:
            assert response.status_code == 200
            lines = [line async for line in response.aiter_lines()]
            assert ": keep-alive" in lines and ": closed authorization_ended" in lines
            assert not any(line.startswith("data: ") for line in lines)


async def test_log_stream_has_a_server_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    await skip_if_database_unavailable()
    email, password = await create_user("managing_director")
    monkeypatch.setattr(business_log_stream, "_MAX_DURATION", timedelta(milliseconds=300))
    async with serve_test_api() as base_url, httpx.AsyncClient(base_url=base_url) as client:
        token = await login_for_token(client, email, password)
        async with asyncio.timeout(4):
            response = await client.get(
                "/api/v1/log-events/stream", params={"action": f"unused.{uuid4().hex}"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 200
        assert response.text.endswith(": closed time_limit\n\n")


async def test_unconfigured_log_retention_archives_without_purging_old_logs() -> None:
    await skip_if_database_unavailable()
    action = f"system.old_log.{uuid4().hex}"
    async with AsyncSessionLocal() as session:
        session.add(
            ActivityLog(
                action=action,
                event_type="system_event",
                severity="INFO",
                comments="Old hot log",
                created_at=utc_now() - timedelta(days=450),
            )
        )
        await session.commit()

        archived = await AuditService(session).archive_logs(
            hot_retention_days=30,
            cutoff_at=utc_now() - timedelta(days=400),
        )
        assert archived >= 1
        await session.commit()

        logs, _ = await AuditService(session).list_logs(
            action=action,
            storage_tier="archive",
        )
        assert len(logs) == 1

        log = logs[0]
        log.retention_until = utc_now() - timedelta(seconds=1)
        await session.flush()
        audit = AuditService(session)
        assert await audit.preview_purge(archive_retention_days=365) == []
        assert await audit.purge_logs(archive_retention_days=365) == 0
        audit.settings = audit.settings.model_copy(update={"log_purge_enabled": True})
        with pytest.raises(AuditRetentionPolicyError, match="scheduled_expiry_policy_required"):
            await audit.purge_logs(archive_retention_days=365)
        assert await session.get(ActivityLog, log.id) is not None


async def test_activity_log_trigger_blocks_unauthorized_mutations_and_deletes() -> None:
    await skip_if_database_unavailable()
    log_id = uuid4()
    initial_deadline = utc_now() + timedelta(days=30)
    async with AsyncSessionLocal() as session:
        session.add(
            ActivityLog(
                id=log_id,
                action=f"audit.immutable.{uuid4().hex}",
                event_type="user_action",
                severity="INFO",
                comments="Original event",
                new_values={"status": "submitted"},
                retention_until=initial_deadline,
            )
        )
        await session.commit()

    for statement in (
        update(ActivityLog).where(ActivityLog.id == log_id).values(action="audit.forged"),
        update(ActivityLog).where(ActivityLog.id == log_id).values(comments="Rewritten"),
        update(ActivityLog).where(ActivityLog.id == log_id).values(new_values={"status": "forged"}),
        update(ActivityLog)
        .where(ActivityLog.id == log_id)
        .values(created_at=utc_now() - timedelta(days=10)),
        update(ActivityLog).where(ActivityLog.id == log_id).values(deleted_at=utc_now()),
        update(ActivityLog)
        .where(ActivityLog.id == log_id)
        .values(retention_until=initial_deadline - timedelta(days=5)),
        update(ActivityLog).where(ActivityLog.id == log_id).values(retention_until=None),
        delete(ActivityLog).where(ActivityLog.id == log_id),
    ):
        async with AsyncSessionLocal() as session:
            with pytest.raises(DBAPIError):
                await session.execute(statement)
            await session.rollback()

    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('garrison.audit_retention_purge', 'allow', true)")
        )
        with pytest.raises(DBAPIError):
            await session.execute(delete(ActivityLog).where(ActivityLog.id == log_id))
        await session.rollback()

    async with AsyncSessionLocal() as session:
        with pytest.raises(DBAPIError):
            await session.execute(text("TRUNCATE TABLE activity_log"))
        await session.rollback()

    # Valid monotonic retention extension and archive transition remain permitted.
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(ActivityLog)
            .where(ActivityLog.id == log_id)
            .values(
                storage_tier="archive",
                archived_at=utc_now(),
                retention_until=initial_deadline + timedelta(days=30),
            )
        )
        await session.commit()
        with pytest.raises(DBAPIError):
            await session.execute(
                update(ActivityLog).where(ActivityLog.id == log_id).values(storage_tier="hot")
            )
        await session.rollback()


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
    admin_email, admin_password = await create_user("managing_director")

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
