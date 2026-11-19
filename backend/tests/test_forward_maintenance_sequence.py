import importlib.util
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "deploy/forward_maintenance_sequence.py"
spec = importlib.util.spec_from_file_location("forward_maintenance_sequence", FILE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Operator:
    def __init__(self, fail=None):
        self.fail = fail
        self.events = []

    def __getattr__(self, name):
        def boundary():
            self.events.append(name)
            if self.fail == name:
                raise ValueError(name)

        return boundary


def test_smoke_precedes_worker_and_ingress_reopening():
    op = Operator()
    module.exercise_sequence(op)
    assert op.events.index("verify_read_only_smoke") < op.events.index("start_and_verify_workers")
    assert op.events.index("start_and_verify_workers") < op.events.index("reopen_business_ingress")
    assert op.events.index("verify_no_writer_sessions") < op.events.index("consume_exact_permit")
    assert op.events.index("consume_exact_permit") < op.events.index("migrate097")
    assert op.events[-1] == "record_completed_release"
    assert not any("backup" in event or "rollback" in event for event in op.events)


@pytest.mark.parametrize(
    "fault",
    [
        "establish_and_verify_ingress_block",
        "stop_and_drain_writers",
        "verify_no_writer_sessions",
        "verify_source093_and_data",
        "consume_exact_permit",
        "migrate097",
        "verify_schema097",
        "start_backend_and_guarded_nginx_only",
        "verify_read_only_smoke",
        "start_and_verify_workers",
        "reopen_business_ingress",
        "record_completed_release",
    ],
)
def test_failure_contains_and_never_records_success(fault):
    op = Operator(fault)
    with pytest.raises(ValueError):
        module.exercise_sequence(op)
    assert op.events[-1] == "stop_and_preserve_failure"
    assert not any("rollback" in event or "downgrade" in event for event in op.events)
    if fault not in {"reopen_business_ingress", "record_completed_release"}:
        assert "reopen_business_ingress" not in op.events
    if fault != "record_completed_release":
        assert "record_completed_release" not in op.events
