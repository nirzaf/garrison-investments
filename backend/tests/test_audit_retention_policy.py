from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert, select, text
from structlog.testing import capture_logs

from app.config import Settings, get_settings
from app.database import AsyncSessionLocal, check_database, engine
from app.models.activity_log import ActivityLog
from app.services import audit_service
from app.services.audit_retention_policy import (
    AuditRetentionPolicyError,
    VerifiedAuditRetentionPolicy,
    audit_writer_policy,
    load_audit_retention_policy,
)
from app.services.audit_service import AuditService
from app.tasks.maintenance import _archive_and_purge_logs
from app.utils.security import utc_now
from scripts import apply_audit_retention
from scripts.preview_audit_retention import category_page


def policy_fields(
    action: str = "finance.receipt", *, mode: str = "scheduled_expiry", days: int = 7
) -> dict:
    return {
        "schema_version": 1,
        "decision_id": "D-28-POLICY",
        "policy_id": "test-retention",
        "revision": "test-1",
        "approved_at": "2025-01-01T00:00:00Z",
        "approval_ref": "test-fixture",
        "mode": mode,
        "default_unknown_disposition": "preserve_and_report",
        "holds_required": False,
        "classes": [
            {
                "class_id": "test-business",
                "predicates": [{"event_type": "audit", "action": action}],
                "start_event": "created_at",
                "duration_unit": "days",
                "duration_value": days,
                "hold_behavior": "no_holds",
            }
        ],
    }


def policy_settings(path: Path, fields: dict, *, enabled: bool = True) -> Settings:
    content = json.dumps(fields).encode()
    path.write_bytes(content)
    return get_settings().model_copy(
        update={
            "audit_retention_policy_path": str(path),
            "audit_retention_policy_sha256": sha256(content).hexdigest(),
            "log_purge_enabled": enabled,
        }
    )


def verified_policy(settings: Settings) -> VerifiedAuditRetentionPolicy:
    verified = load_audit_retention_policy(
        settings.audit_retention_policy_path, settings.audit_retention_policy_sha256
    )
    assert verified is not None
    return verified


@pytest.fixture
async def database():
    await engine.dispose()
    if not await check_database():
        pytest.skip("database is not available")
    yield
    await engine.dispose()


@pytest.mark.parametrize(
    ("rule", "month", "day"),
    [("february_28", 2, 28), ("march_1", 3, 1)],
)
def test_policy_calendar_years_use_an_explicit_utc_leap_rule(
    tmp_path: Path, rule: str, month: int, day: int
) -> None:
    fields = policy_fields()
    fields["classes"][0].update(
        duration_unit="calendar_years", duration_value=7, leap_day_rule=rule
    )
    verified = verified_policy(policy_settings(tmp_path / "policy.json", fields))
    start = datetime(2024, 3, 1, 1, 34, tzinfo=timezone(timedelta(hours=2)))
    expected = datetime(2031, month, day, 23, 34, tzinfo=UTC)
    assert verified.policy.deadline("finance.receipt", "audit", start, None) == expected
    longer = datetime(2033, 4, 1, tzinfo=UTC)
    assert verified.policy.deadline("finance.receipt", "audit", start, longer) == longer
    assert verified.policy.deadline("finance.receipt", "api_request", start, None) is None
    assert verified.policy.deadline("other.receipt", "audit", start, None) is None


def test_policy_requires_exact_digest_and_nonoverlapping_known_fields(tmp_path: Path) -> None:
    assert load_audit_retention_policy(None, None) is None
    assert load_audit_retention_policy("", "") is None
    policy_path = tmp_path / "policy.json"
    settings = policy_settings(policy_path, policy_fields())
    verified_policy(settings)
    policy_path.write_text("{}", encoding="utf-8")
    with pytest.raises(AuditRetentionPolicyError, match="digest_mismatch"):
        verified_policy(settings)
    assert audit_writer_policy(str(policy_path), settings.audit_retention_policy_sha256) is None
    policy_settings(policy_path, policy_fields())
    assert audit_writer_policy(str(policy_path), settings.audit_retention_policy_sha256) is not None

    fields = policy_fields()
    fields["classes"][0]["predicates"].append({"event_type": "audit", "action_prefix": "finance."})
    with pytest.raises(AuditRetentionPolicyError, match="schema_invalid"):
        verified_policy(policy_settings(policy_path, fields))
    fields = policy_fields()
    fields["classes"][0]["duration_value"] = "7"
    with pytest.raises(AuditRetentionPolicyError, match="schema_invalid"):
        verified_policy(policy_settings(policy_path, fields))
    fields = policy_fields()
    fields["holds_required"] = True
    fields["classes"][0]["hold_behavior"] = "retain_held"
    with pytest.raises(AuditRetentionPolicyError, match="hold_schema_unavailable"):
        verified_policy(policy_settings(policy_path, fields))


async def test_writer_uses_policy_and_protects_unclassified_records(
    database, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    settings = policy_settings(tmp_path / "policy.json", policy_fields(action))
    monkeypatch.setattr(audit_service, "get_settings", lambda: settings)
    async with AsyncSessionLocal() as session:
        audit = AuditService(session)
        await audit.record(action=action, event_type="audit")
        await audit.record(action=action, event_type="api_request")
        await session.flush()
        logs, _ = await audit.list_logs(action=action)
        deadlines = {log.event_type: log for log in logs}
        assert deadlines["audit"].retention_until == deadlines["audit"].created_at + timedelta(
            days=7
        )
        assert deadlines["api_request"].retention_until is None


async def test_preview_covers_complete_population_and_purge_is_bounded(
    database, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    settings = policy_settings(tmp_path / "policy.json", policy_fields(action))
    cutoff = utc_now()
    created = cutoff - timedelta(days=400)
    base = {
        "event_type": "audit",
        "action": action,
        "created_at": created,
        "archived_at": cutoff - timedelta(days=366),
        "storage_tier": "archive",
        "retention_until": cutoff,
    }
    async with AsyncSessionLocal() as session:
        ids = [uuid4() for _ in range(1002)]
        await session.execute(insert(ActivityLog), [{**base, "id": id_} for id_ in ids])
        protected: dict[UUID, dict[str, object]] = {
            uuid4(): {"retention_until": None},
            uuid4(): {"retention_until": cutoff + timedelta(seconds=1)},
            uuid4(): {"retention_until": created + timedelta(days=1)},
            uuid4(): {"action": f"{action}.unknown"},
            uuid4(): {"archived_at": cutoff - timedelta(days=365)},
        }
        await session.execute(
            insert(ActivityLog),
            [{**base, **overrides, "id": id_} for id_, overrides in protected.items()],
        )
        audit = AuditService(session)
        audit.settings = settings
        verified = audit.configured_retention_policy()
        counts = await audit.retention_counts(verified, cutoff)
        assert counts["eligible"] == 1002
        assert counts["shorter_than_policy"] == 1
        assert counts["protected"] >= len(protected)
        first, cursor = await category_page(
            audit, verified, cutoff, "eligible", limit=1000, after=None
        )
        assert len(first) == 1000 and cursor is not None
        second, end = await category_page(
            audit, verified, cutoff, "eligible", limit=1000, after=UUID(cursor)
        )
        assert end is None
        assert [row["id"] for row in first + second] == [str(value) for value in sorted(ids)]
        assert await audit.purge_logs(cutoff_at=cutoff) == 1000
        assert await audit.purge_logs(cutoff_at=cutoff) == 2
        remaining = await session.scalars(
            select(ActivityLog.id).where(ActivityLog.id.in_(protected))
        )
        assert set(remaining) == set(protected)


async def test_calendar_sql_matches_python_with_non_utc_database_session(
    database, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    fields = policy_fields(action)
    fields["classes"][0].update(
        duration_unit="calendar_years", duration_value=1, leap_day_rule="march_1"
    )
    verified = verified_policy(policy_settings(tmp_path / "policy.json", fields))
    created = datetime(2024, 2, 29, 1, 35, tzinfo=UTC)
    id_ = uuid4()
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET LOCAL TIME ZONE 'America/New_York'"))
        session.add(ActivityLog(id=id_, event_type="audit", action=action, created_at=created))
        await session.flush()
        calculated = await session.scalar(
            select(verified.policy.sql_deadline()).where(ActivityLog.id == id_)
        )
        assert calculated == datetime(2025, 3, 1, 1, 35, tzinfo=UTC)
        assert calculated == verified.policy.deadline(action, "audit", created, None)


async def test_task_rolls_back_archival_when_expiry_policy_is_missing(
    database, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(
        update={
            "log_purge_enabled": True,
            "audit_retention_policy_path": None,
            "audit_retention_policy_sha256": None,
        }
    )
    monkeypatch.setattr(audit_service, "get_settings", lambda: settings)
    id_ = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        session.add(
            ActivityLog(
                id=id_, action="test.retention.failure", created_at=utc_now() - timedelta(days=90)
            )
        )
    with capture_logs() as logs, pytest.raises(AuditRetentionPolicyError, match="scheduled_expiry"):
        await _archive_and_purge_logs()
    assert [(log["event"], log["failed"]) for log in logs] == [("logs_retention_failed", 1)]
    async with AsyncSessionLocal() as session:
        row = await session.get(ActivityLog, id_)
        assert row is not None and row.storage_tier == "hot"


async def test_retain_only_task_archives_and_records_policy_without_expiring(
    database, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    settings = policy_settings(
        tmp_path / "policy.json", policy_fields(action, mode="retain_only"), enabled=False
    )
    monkeypatch.setattr(audit_service, "get_settings", lambda: settings)
    id_ = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        session.add(
            ActivityLog(
                id=id_,
                action=action,
                created_at=utc_now() - timedelta(days=400),
                retention_until=utc_now() - timedelta(days=2),
            )
        )
    with capture_logs() as logs:
        await _archive_and_purge_logs()
    assert logs[0]["event"] == "logs_retention_completed"
    assert logs[0]["policy_sha256"] == settings.audit_retention_policy_sha256
    assert logs[0]["mode"] == "retain_only"
    assert logs[0]["archived"] >= 1 and logs[0]["deleted"] == 0
    assert logs[0]["scanned"] == logs[0]["protected"]
    async with AsyncSessionLocal() as session:
        audit = AuditService(session)
        rows, _ = await audit.list_logs(action=action, storage_tier="archive")
        assert [row.id for row in rows] == [id_]
        audit.settings = settings.model_copy(update={"log_purge_enabled": True})
        with pytest.raises(AuditRetentionPolicyError, match="scheduled_expiry"):
            await audit.purge_logs()


async def test_extension_plan_checks_exact_bytes_rejects_stale_batch_and_resumes(
    database, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    settings = policy_settings(tmp_path / "policy.json", policy_fields(action))
    monkeypatch.setattr(audit_service, "get_settings", lambda: settings)
    cutoff = utc_now()
    ids = sorted(uuid4() for _ in range(2))
    async with AsyncSessionLocal() as session, session.begin():
        for id_ in ids:
            session.add(
                ActivityLog(id=id_, event_type="audit", action=action, comments="private-fixture")
            )
    async with AsyncSessionLocal() as session:
        plan = await apply_audit_retention.build_extension_plan(
            session, verified_policy(settings), utc_now()
        )
        assert [entry.record_id for entry in plan.entries] == ids
    path = tmp_path / "plan.json"
    digest = apply_audit_retention.write_extension_plan(path, plan)
    assert "private-fixture" not in path.read_text()
    assert apply_audit_retention.read_extension_plan(path, digest) == (plan, digest)
    with pytest.raises(apply_audit_retention.RetentionPlanError, match="SHA-256"):
        apply_audit_retention.read_extension_plan(path, "0" * 64)
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(text("SET TRANSACTION READ ONLY"))
        assert (
            await apply_audit_retention.execute_batch(
                session, plan, digest, 1, plan.entries, approval_reference=None
            )
            == "ready"
        )
    async with AsyncSessionLocal() as session, session.begin():
        first = await session.get(ActivityLog, ids[0])
        assert first is not None and first.retention_until is None
        assert (
            await apply_audit_retention.execute_batch(
                session, plan, digest, 1, plan.entries[:1], approval_reference="test-approval"
            )
            == "applied"
        )
        second = await session.get(ActivityLog, ids[1])
        assert second is not None
        second.retention_until = cutoff + timedelta(days=60)
    async with AsyncSessionLocal() as session, session.begin():
        assert (
            await apply_audit_retention.execute_batch(
                session, plan, digest, 1, plan.entries[:1], approval_reference="test-approval"
            )
            == "already_applied"
        )
        with pytest.raises(apply_audit_retention.RetentionPlanError, match="stale"):
            await apply_audit_retention.execute_batch(
                session, plan, digest, 2, plan.entries[1:], approval_reference="test-approval"
            )
        second = await session.get(ActivityLog, ids[1])
        assert second is not None and second.retention_until == cutoff + timedelta(days=60)
        receipts = (
            await AuditService(session).list_logs(action="maintenance.audit_retention_extension")
        )[0]
        assert (
            sum(
                (receipt.context_payload or {}).get("plan_sha256") == digest
                for receipt in receipts
            )
            == 1
        )


async def test_purge_skips_a_record_locked_by_an_extension(
    database, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    action = f"test.audit.{uuid4().hex}"
    old = policy_settings(tmp_path / "old.json", policy_fields(action))
    new = policy_settings(tmp_path / "new.json", policy_fields(action, days=730))
    monkeypatch.setattr(audit_service, "get_settings", lambda: new)
    cutoff = utc_now()
    id_ = uuid4()
    async with AsyncSessionLocal() as session, session.begin():
        session.add(
            ActivityLog(
                id=id_,
                event_type="audit",
                action=action,
                created_at=cutoff - timedelta(days=400),
                archived_at=cutoff - timedelta(days=366),
                storage_tier="archive",
                retention_until=cutoff,
            )
        )
    async with AsyncSessionLocal() as extension, AsyncSessionLocal() as purge:
        plan = await apply_audit_retention.build_extension_plan(
            extension, verified_policy(new), cutoff
        )
        assert [entry.record_id for entry in plan.entries] == [id_]
        digest = sha256(plan.model_dump_json().encode()).hexdigest()
        assert (
            await apply_audit_retention.execute_batch(
                extension, plan, digest, 1, plan.entries, approval_reference="test-approval"
            )
            == "applied"
        )
        auditor = AuditService(purge)
        auditor.settings = old
        await purge.execute(text("SET LOCAL statement_timeout = '2s'"))
        assert await auditor.purge_logs(cutoff_at=cutoff) == 0
        await extension.commit()
        assert await auditor.purge_logs(cutoff_at=cutoff) == 0
        row = await purge.get(ActivityLog, id_)
        assert row is not None and row.retention_until is not None and row.retention_until > cutoff
