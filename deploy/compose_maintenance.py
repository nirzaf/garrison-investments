"""Concrete Docker boundary for an already-reviewed Compose inventory.

Not enrolled in the host dispatcher. Does not discover/authorize arbitrary services,
install ingress policy, migrate, or publish. Operator supplies exact container IDs and
expected Compose labels. Refuses topology drift, forced termination and busy workers.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable


class ComposeMaintenance:
    def __init__(
        self, project: str, containers: dict[str, str], *, timeout: float = 30
    ):
        if set(containers) not in (
            {"nginx", "backend", "celery_worker"},
            {"nginx", "backend", "celery_worker", "celery_beat"},
        ):
            raise ValueError(
                "This bounded adapter supports nginx/backend/one worker and optional beat only"
            )
        self.project, self.containers, self.timeout = (
            project,
            containers.copy(),
            timeout,
        )
        self.ids: dict[str, str] = {}

    def command(self, *args: str) -> str:
        return subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=self.timeout,
        ).stdout

    def snapshot(self, service: str) -> dict:
        obj = json.loads(self.command("inspect", self.containers[service]))[0]
        labels = obj["Config"].get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != self.project
            or labels.get("com.docker.compose.service") != service
        ):
            raise ValueError("Container identity/Compose label mismatch")
        if obj["HostConfig"]["RestartPolicy"]["Name"] not in ("no", ""):
            raise ValueError("Automatic restart policy is not qualified")
        # Fixture has no host listeners. Production ingress must use a separate
        # reviewed installed policy; this adapter intentionally refuses its ports.
        if obj["HostConfig"].get("PortBindings"):
            raise ValueError("Published ports outside local fixture boundary")
        previous = self.ids.setdefault(service, obj["Id"])
        if previous != obj["Id"]:
            raise ValueError("Container replaced after inventory")
        return obj

    def assert_inventory(self) -> None:
        for service in self.containers:
            self.snapshot(service)
        actual = set(
            self.command(
                "ps",
                "-aq",
                "--no-trunc",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            ).split()
        )
        if actual != set(self.ids.values()):
            raise ValueError("Unknown project container; inventory is not complete")

    def stop_warm(self, service: str) -> None:
        self.snapshot(service)
        if not self.snapshot(service)["State"]["Running"]:
            return
        self.command("kill", "--signal=TERM", self.ids[service])
        deadline = time.monotonic() + self.timeout
        while self.snapshot(service)["State"]["Running"]:
            if time.monotonic() >= deadline:
                raise TimeoutError("Warm stop incomplete; never force-kill")
            time.sleep(0.1)

    def assert_worker_idle(self) -> None:
        worker = self.ids["celery_worker"]
        for operation in ("active", "reserved", "scheduled"):
            responses = json.loads(
                self.command(
                    "exec",
                    worker,
                    "celery",
                    "-A",
                    "app.tasks.celery_app.celery_app",
                    "inspect",
                    operation,
                    "--json",
                    "--timeout=2",
                )
            )
            if not isinstance(responses, dict) or len(responses) != 1:
                raise ValueError("Exact one-worker response required")
            if any(
                not isinstance(tasks, list) or tasks for tasks in responses.values()
            ):
                raise ValueError("Worker is not idle; drain not complete")

    def drain_fixture(self) -> None:
        self.assert_inventory()
        self.stop_warm("nginx")
        if "celery_beat" in self.containers:
            self.stop_warm("celery_beat")
        self.assert_worker_idle()
        self.stop_warm("celery_worker")
        self.stop_warm("backend")
        if any(self.snapshot(s)["State"]["Running"] for s in self.containers):
            raise ValueError("Writer remains running")

    def wait_beat_started(self) -> None:
        """Require this exact container start's structured lifecycle event, not old logs."""
        initial = self.snapshot("celery_beat")
        started = initial["State"]["StartedAt"]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            current = self.snapshot("celery_beat")
            if (
                not current["State"]["Running"]
                or current["State"]["StartedAt"] != started
            ):
                raise ValueError("Beat exited or restarted during readiness")
            result = subprocess.run(
                ["docker", "logs", "--since", started, self.ids["celery_beat"]],
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            for line in (result.stdout + result.stderr).splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if (
                    isinstance(event, dict)
                    and event.get("logger") == "celery.beat"
                    and (event.get("message") == "beat: Starting...")
                ):
                    return
            time.sleep(0.1)
        raise TimeoutError("Current beat startup event absent; leave ingress blocked")

    def guarded_restart_fixture(self, read_only_smoke: Callable[[], None]) -> None:
        self.assert_inventory()
        if any(self.snapshot(s)["State"]["Running"] for s in self.containers):
            raise ValueError("Expected fully stopped fixture")
        try:
            for service in ("backend", "nginx"):
                self.command("start", self.ids[service])
            read_only_smoke()  # Installed guard is verified, never self-asserted Boolean.
            self.command("start", self.ids["celery_worker"])
            if "celery_beat" in self.containers:
                self.command("start", self.ids["celery_beat"])
                self.wait_beat_started()
        except BaseException as original:
            failures = []
            for service in ("nginx", "celery_beat", "celery_worker", "backend"):
                if service in self.containers:
                    try:
                        self.stop_warm(service)
                    except BaseException as failure:  # noqa: BLE001 - grouped below
                        failures.append(failure)
            if failures:
                raise BaseExceptionGroup(
                    "Restart failed; containment incomplete", [original, *failures]
                )
            raise
