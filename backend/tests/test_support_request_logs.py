import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.api.v1.support import SESSION_COOKIE
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.support_cases import SupportCaseRequest, SupportLogStream, SupportOperatorGrant
from app.models.support_identity import SupportSession
from app.services import support_log_stream
from app.services.support_request_logs import (
    SupportRequestLogQuery,
    SupportRequestLogStreamQuery,
    project_request_logs,
)
from app.utils.exceptions import AppException
from app.utils.security import utc_now
from tests.test_auth import isolated_engine_pool as isolated_engine_pool
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_cases import CASES, case_operator
from tests.test_support_identity import client
from tests.test_support_identity import enabled as enabled


@pytest.mark.parametrize(
    "patch",
    [
        {"request_id": 'label"} | {method=~".*"}'},
        {"started_at": "2026-11-17T00:00:00"},
        {"ended_at": "2026-11-18T01:00:00+00:00"},
        {"ended_at": "2026-11-17T00:00:00+00:00"},
        {"limit": 101},
        {"status_code": 600},
        {"search": "unbounded text"},
    ],
)
def test_support_log_filter_rejects_invalid_or_unbounded_selectors(patch: dict) -> None:
    payload = {
        "request_id": uuid4().hex,
        "started_at": "2026-11-17T00:00:00+00:00",
        "ended_at": "2026-11-17T01:00:00+00:00",
    }
    with pytest.raises(ValidationError):
        SupportRequestLogQuery.model_validate({**payload, **patch})


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool")
async def test_support_request_logs_exclude_raw_or_unrelated_evidence() -> None:
    await skip_if_database_unavailable()
    start = datetime(2026, 11, 17, tzinfo=UTC)
    request_id = str(uuid4())
    marker = "SYNTHETIC-PRIVATE-PAYROLL-AND-OTP"
    patches: tuple[dict[str, object], ...] = (
        {},
        {"action": "http.app_exception", "status_code": 403, "http_method": "GET"},
        {"action": "hr.payroll.approved"},
        {"request_id": uuid4().hex},
        {"deleted_at": start},
        {"created_at": start - timedelta(days=2)},
        {"entity_type": "employee"},
    )
    async with AsyncSessionLocal() as session:
        for index, patch in enumerate(patches):
            session.add(
                ActivityLog(
                    **{
                        "action": "http.request",
                        "entity_type": "request",
                        "created_at": start + timedelta(minutes=index),
                        "request_id": request_id,
                        "http_method": "PRIVATE-MARKER",
                        "status_code": 200,
                        "endpoint": f"/example?token={marker}",
                        "comments": marker,
                        "context_payload": {"password": marker},
                        "new_values": {"payroll": marker},
                        **patch,
                    }
                )
            )
        await session.flush()
        full = SupportRequestLogQuery(
            request_id=request_id, started_at=start, ended_at=start + timedelta(hours=1)
        )
        result = await project_request_logs(session, full)
        assert [event.kind for event in result.events] == ["handled_error", "request"]
        assert [event.method for event in result.events] == ["GET", None]
        assert not result.truncated
        assert marker not in result.model_dump_json()
        assert "PRIVATE-MARKER" not in result.model_dump_json()
        limited = await project_request_logs(session, full.model_copy(update={"limit": 1}))
        assert len(limited.events) == 1 and limited.truncated
        denied = await project_request_logs(session, full.model_copy(update={"status_code": 403}))
        assert [event.status_code for event in denied.events] == [403]
        await session.rollback()


async def _stream_case(browser: httpx.AsyncClient) -> tuple[UUID, UUID, str, list[UUID]]:
    operator = await case_operator(browser)
    opened = await browser.post(
        CASES,
        json={"external_ref": f"stream-{uuid4()}", "severity": "high", "reason_code": "access"},
    )
    assert opened.status_code == 201
    case = UUID(opened.json()["id"])
    source = uuid4().hex
    events = [uuid4(), uuid4()]
    async with AsyncSessionLocal() as db:
        db.add(SupportOperatorGrant(operator_id=operator, capability="logs.runtime"))
        db.add(SupportOperatorGrant(operator_id=operator, capability="logs.stream"))
        db.add(SupportCaseRequest(case_id=case, request_id=source))
        for index, event_id in enumerate(events):
            db.add(ActivityLog(
                id=event_id, action="http.request", entity_type="request", http_method="GET",
                request_id=source, created_at=utc_now() - timedelta(seconds=10 - index),
                endpoint="/private?token=private-stream-marker", status_code=200,
            ))
        await db.commit()
    return operator, case, source, events


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_case_stream_limit_resume_revocation_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setattr(support_log_stream, "_POLL_SECONDS", 0.02)
    async with client() as browser:
        operator, case, source, events = await _stream_case(browser)
        token = browser.cookies[SESSION_COOKIE]
        query = SupportRequestLogStreamQuery(request_id=source)

        async def open_stream():
            return await support_log_stream.open_case_log_stream(
                token, case, query, uuid4().hex, events[0]
            )

        outcomes = await asyncio.gather(*(open_stream() for _ in range(3)), return_exceptions=True)
        admitted = [item for item in outcomes if isinstance(item, support_log_stream.CaseLogStream)]
        denied = [item for item in outcomes if isinstance(item, AppException)]
        assert len(admitted) == 2 and [item.status_code for item in denied] == [429]
        async with AsyncSessionLocal() as db:
            session = await db.scalar(
                select(SupportSession).where(SupportSession.operator_id == operator)
            )
            assert session is not None
            original_idle = session.last_seen_at
        first, second = [
            support_log_stream.case_log_events(lease, token, case, source) for lease in admitted
        ]
        try:
            batch = await anext(first)
            assert f"id: {events[1]}" in batch and str(events[0]) not in batch
            event = json.loads(batch.splitlines()[1].removeprefix("data: "))
            assert event["status_code"] == 200 and "private-stream-marker" not in batch
            assert await anext(second) == batch
            async with AsyncSessionLocal() as db:
                await db.execute(delete(SupportOperatorGrant).where(
                    SupportOperatorGrant.operator_id == operator,
                    SupportOperatorGrant.capability == "logs.stream",
                ))
                await db.commit()
            assert await anext(first) == ": keep-alive\n\n"
            terminal = await asyncio.wait_for(anext(first), timeout=4)
            assert "access_ended" in terminal and str(events[1]) not in terminal
            async with AsyncSessionLocal() as db:
                session = await db.scalar(
                    select(SupportSession).where(SupportSession.operator_id == operator)
                )
                assert session is not None and session.last_seen_at == original_idle
                session.last_seen_at = utc_now() - timedelta(minutes=16)
                db.add(SupportOperatorGrant(operator_id=operator, capability="logs.stream"))
                await db.commit()
            assert await anext(second) == ": keep-alive\n\n"
            terminal = await asyncio.wait_for(anext(second), timeout=4)
            assert "session_ended" in terminal and str(events[1]) not in terminal
        finally:
            await first.aclose()
            await second.aclose()
            for lease in admitted:
                await support_log_stream.close_case_log_stream(lease.id)
        async with AsyncSessionLocal() as db:
            leases = (await db.scalars(
                select(SupportLogStream).where(SupportLogStream.case_id == case)
            )).all()
            assert len(leases) == 2 and all(row.closed_at is not None for row in leases)


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_case_stream_http_is_case_scoped_and_finishes_with_a_typed_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    monkeypatch.setattr(support_log_stream, "_MAX_DURATION", timedelta(milliseconds=400))
    monkeypatch.setattr(support_log_stream, "_POLL_SECONDS", 0.02)
    async with client() as browser, client() as outsider:
        _, case, source, events = await _stream_case(browser)
        other = await case_operator(outsider)
        async with AsyncSessionLocal() as db:
            db.add(SupportOperatorGrant(operator_id=other, capability="logs.runtime"))
            db.add(SupportOperatorGrant(operator_id=other, capability="logs.stream"))
            await db.commit()
        endpoint = f"{CASES}/{case}/logs/stream"
        params = {"request_id": source}
        assert (await outsider.get(endpoint, params=params)).status_code == 404
        assert (
            await browser.get(endpoint, params=params, headers={"Sec-Fetch-Site": "same-site"})
        ).status_code == 403
        assert (
            await browser.get(endpoint, params=params, headers={"Last-Event-ID": str(uuid4())})
        ).status_code == 409
        response = await browser.get(
            endpoint, params=params, headers={"Last-Event-ID": str(events[0])}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["x-accel-buffering"] == "no"
        assert str(events[1]) in response.text and str(events[0]) not in response.text
        assert 'event: closed\ndata: {"reason": "time_limit"}' in response.text
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SupportOperatorGrant).where(
                SupportOperatorGrant.capability == "logs.stream",
                SupportOperatorGrant.operator_id.in_(
                    select(SupportLogStream.operator_id).where(SupportLogStream.case_id == case)
                ),
            ))
            await db.commit()
        assert (await browser.get(endpoint, params=params)).status_code == 403
