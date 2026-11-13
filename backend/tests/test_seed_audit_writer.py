from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest

seed = import_module("scripts.seed")


async def test_seed_activity_logs_use_the_policy_aware_audit_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[dict[str, object]] = []

    class Session:
        async def scalar(self, _statement: object) -> None:
            return None

    class AuditWriter:
        def __init__(self, _session: Session) -> None:
            pass

        async def record(self, **record: object) -> None:
            records.append(record)

    monkeypatch.setattr(seed, "AuditService", AuditWriter)
    users = {
        seed.DEFAULT_ADMIN_EMAIL: SimpleNamespace(id=uuid4()),
        "engineer.test@garrisons.lk": SimpleNamespace(id=uuid4()),
        "pm.test@garrisons.lk": SimpleNamespace(id=uuid4()),
        "storekeeper.test@garrisons.lk": SimpleNamespace(id=uuid4()),
    }

    await seed.seed_activity_logs(Session(), users, {})

    assert len(records) == 6
    assert {record["event_type"] for record in records} == {"audit"}
    assert {record["action"] for record in records} == {
        "user_login",
        "report_create",
        "report_submit",
        "approval_decision",
        "inventory_movement",
        "seed_data",
    }


async def test_demo_seed_refuses_production_before_opening_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed, "get_settings", lambda: SimpleNamespace(app_env="production"))

    with pytest.raises(SystemExit, match="Demo data can only be seeded"):
        await seed.seed_launch_data()
