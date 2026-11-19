"""Executable synthetic 093→097 dispatcher; NEVER accepts a production topology.

Fixed Docker commands, protected local policy/permit, actual PostgreSQL migration,
Compose drain/restart and TLS smoke. No GitHub claim, publication or host enrollment.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import time
from pathlib import Path

from compose_maintenance import ComposeMaintenance
from forward_adapter_journal import DurableAttempt
from forward_release_contract import consume_permit
from maintenance_ingress import GUARD


def read_policy(path: Path) -> dict:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Fixture policy must be private and operator-owned")
    policy = json.loads(path.read_text())
    if set(policy) != {
        "project",
        "containers",
        "database",
        "network",
        "config",
        "image",
        "identity",
    }:
        raise ValueError("Unexpected policy fields")
    if not policy["project"].startswith("garrison-f097-"):
        raise ValueError("Only uniquely named synthetic fixture projects are supported")
    return policy


def dispatch(policy_path: Path, state: Path) -> None:
    policy = read_policy(policy_path)
    adapter = ComposeMaintenance(policy["project"], policy["containers"])
    adapter.assert_inventory()
    docker = adapter.command
    network = json.loads(docker("network", "inspect", policy["network"]))[0]
    if not network["Internal"] or network["Name"] != policy["project"] + "-private":
        raise ValueError("Internal disposable network required")
    database = json.loads(docker("inspect", policy["database"]))[0]
    if (
        database["HostConfig"].get("PortBindings")
        or database["Name"] != "/" + policy["project"] + "-db"
    ):
        raise ValueError("Disposable unpublished database required")
    for service in policy["containers"]:
        obj = adapter.snapshot(service)
        if obj["Image"] != policy["image"] and service != "nginx":
            raise ValueError("Exact application image mismatch")
        if set(obj["NetworkSettings"]["Networks"]) != {policy["network"]}:
            raise ValueError("Unexpected application network")
    config = Path(policy["config"])
    config_info = config.lstat()
    if not stat.S_ISREG(config_info.st_mode) or config_info.st_uid != os.getuid():
        raise ValueError("Operator-owned fixture ingress config required")
    guarded = config.read_text()
    if guarded.count(GUARD) != 1:
        raise ValueError("Exact fixture ingress guard required")

    # No arbitrary SQL, migration revision, command, URL or shell supplied by policy.
    def sql(query: str) -> str:
        return docker(
            "exec",
            database["Id"],
            "psql",
            "-U",
            "fixture",
            "-d",
            "fixture",
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            query,
        ).strip()

    def source() -> str:
        return sql("SELECT version_num FROM alembic_version")

    if source() != "202605310093":
        raise ValueError("Exact source093 required; never replay097")
    journal = DurableAttempt(
        state, {"scope": "synthetic-only", **policy["identity"]}, owner_uid=os.getuid()
    )
    try:
        journal.append("ingress_guard_verified")
        adapter.drain_fixture()
        if (
            sql(
                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                "AND pid<>pg_backend_pid() AND backend_type='client backend'"
            )
            != "0"
        ):
            raise ValueError("Database writers remain")
        if source() != "202605310093":
            raise ValueError("Source schema changed before consumption")
        journal.append("drained093")
        consume_permit(state, owner_uid=os.getuid(), **policy["identity"])
        journal.append("permit_consumed_migration_intent")
        # Reuse exactly the fixture API mount and environment; never copy production data.
        backend = adapter.snapshot("backend")
        env = backend["Config"]["Env"]
        if (
            "DATABASE_URL=postgresql+asyncpg://fixture:synthetic-only@db:5432/fixture"
            not in env
        ):
            raise ValueError("Only synthetic database credentials accepted")
        args = [
            "run",
            "--rm",
            "--network",
            policy["network"],
            "--volumes-from",
            adapter.ids["backend"] + ":ro",
        ]
        for item in env:
            args += ["-e", item]
        docker(*args, policy["image"], "alembic", "upgrade", "202605310097")
        if source() != "202605310097":
            raise ValueError("Migration did not reach097")
        journal.append("migration097_verified")

        def request(path: str) -> str:
            return docker(
                "exec",
                adapter.ids["backend"],
                "curl",
                "-ksS",
                "--max-time",
                "3",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "https://ingress:8443" + path,
            )

        def smoke() -> None:
            deadline = time.monotonic() + 25
            while True:
                try:
                    if request("/health/readiness") == "200":
                        break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("Readiness not reached")
                time.sleep(0.2)
            for path in ("/api/v1/projects", "/api/v1/auth/login", "/api/v1/support"):
                if request(path) != "503":
                    raise ValueError("Guarded business API unexpectedly reachable")
            journal.append("guarded_smoke_verified")

        adapter.guarded_restart_fixture(smoke)
        journal.append("writers_restarted_after_smoke")
        config.write_text(guarded.replace(GUARD, ""))
        docker("exec", adapter.ids["nginx"], "nginx", "-t")
        docker("exec", adapter.ids["nginx"], "nginx", "-s", "reload")
        journal.append("synthetic_dispatch_completed")
    except BaseException as original:
        failures = []
        for service in ("nginx", "celery_beat", "celery_worker", "backend"):
            try:
                adapter.stop_warm(service)
            except BaseException as failure:  # noqa: BLE001 - grouped and re-raised
                failures.append(failure)
        journal.append("containment_unknown" if failures else "contained_failure")
        if failures:
            raise BaseExceptionGroup(
                "Dispatch and containment failed", [original, *failures]
            )
        raise
    finally:
        journal.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture-policy", required=True, type=Path)
    parser.add_argument("--fixture-state", required=True, type=Path)
    arguments = parser.parse_args()
    dispatch(arguments.fixture_policy, arguments.fixture_state)
