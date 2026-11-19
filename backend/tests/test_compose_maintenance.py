import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "deploy/compose_maintenance.py"
spec = importlib.util.spec_from_file_location("adapter", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def adapter():
    return module.ComposeMaintenance(
        "fixture", {"nginx": "nginx", "backend": "backend", "celery_worker": "worker"}
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("restart", "always"),
        ("ports", {"8000/tcp": []}),
        ("project", "other"),
        ("service", "other"),
    ],
)
def test_topology_drift_refused(field, value):
    a = adapter()
    fixture = dict(restart="no", ports={}, project="fixture", service="backend")
    fixture[field] = value
    obj = {
        "Id": "fixed",
        "Config": {
            "Labels": {
                "com.docker.compose.project": fixture["project"],
                "com.docker.compose.service": fixture["service"],
            }
        },
        "HostConfig": {
            "RestartPolicy": {"Name": fixture["restart"]},
            "PortBindings": fixture["ports"],
        },
    }
    a.command = lambda *args: json.dumps([obj])
    with pytest.raises(ValueError):
        a.snapshot("backend")


@pytest.mark.parametrize(
    "response", [{}, {"worker": [{}]}, {"worker": "invalid"}, {"worker1": [], "worker2": []}]
)
def test_busy_missing_or_ambiguous_worker_refused(response):
    a = adapter()
    a.ids["celery_worker"] = "fixture"
    a.command = lambda *args: json.dumps(response)
    with pytest.raises(ValueError):
        a.assert_worker_idle()


def test_missing_beat_readiness_contains_all_services():
    a = module.ComposeMaintenance(
        "fixture", {"nginx": "n", "backend": "b", "celery_worker": "w", "celery_beat": "s"}
    )
    a.ids = a.containers.copy()
    a.assert_inventory = lambda: None
    a.snapshot = lambda service: {"State": {"Running": False}}
    a.command = lambda *args: ""
    stopped = []
    a.stop_warm = lambda service: stopped.append(service)

    def missing():
        raise TimeoutError("missing current startup")

    a.wait_beat_started = missing
    with pytest.raises(TimeoutError):
        a.guarded_restart_fixture(lambda: None)
    assert stopped == ["nginx", "celery_beat", "celery_worker", "backend"]


def test_containment_attempts_remaining_services_after_stop_failure():
    a = module.ComposeMaintenance(
        "fixture", {"nginx": "n", "backend": "b", "celery_worker": "w", "celery_beat": "s"}
    )
    a.ids = a.containers.copy()
    a.assert_inventory = lambda: None
    a.snapshot = lambda service: {"State": {"Running": False}}
    a.command = lambda *args: ""
    stopped = []

    def failure():
        raise TimeoutError("readiness")

    def stop(service):
        stopped.append(service)
        if service == "celery_beat":
            raise TimeoutError("warm stop")

    a.wait_beat_started = failure
    a.stop_warm = stop
    with pytest.raises(BaseExceptionGroup):
        a.guarded_restart_fixture(lambda: None)
    assert stopped == ["nginx", "celery_beat", "celery_worker", "backend"]
