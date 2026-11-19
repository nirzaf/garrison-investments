import importlib.util
import json
import os
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "deploy/forward_adapter_journal.py"
spec = importlib.util.spec_from_file_location("journal", PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path):
    directory = tmp_path / "operator" / "release"
    directory.mkdir(parents=True, mode=0o700)
    return directory, module.DurableAttempt(
        directory, {"fixture": "synthetic"}, owner_uid=os.getuid()
    )


def events(directory):
    return [
        json.loads(line) for line in (directory / "forward097.attempt").read_text().splitlines()
    ]


def test_success_is_durable_and_not_replayable(tmp_path):
    directory, journal = fixture(tmp_path)
    called = []
    functions = {p: lambda p=p: called.append(p) for p in set(module.PHASES)}
    functions["stop_and_preserve_failure"] = lambda: called.append("containment")
    try:
        module.exercise_trusted_adapter(journal, functions)
    finally:
        journal.close()
    assert called == list(module.PHASES)
    assert events(directory)[-1]["event"] == "attempt_completed"
    with pytest.raises(FileExistsError):
        module.DurableAttempt(directory, {}, owner_uid=os.getuid())


@pytest.mark.parametrize("fault", sorted(set(module.PHASES)))
def test_every_boundary_failure_preserves_marker_and_contains(tmp_path, fault):
    directory, journal = fixture(tmp_path)
    called = []

    def invoke(phase):
        called.append(phase)
        if phase == fault:
            raise RuntimeError("fixture fault")

    functions = {p: lambda p=p: invoke(p) for p in set(module.PHASES)}
    functions["stop_and_preserve_failure"] = lambda: called.append("contained")
    try:
        with pytest.raises(RuntimeError):
            module.exercise_trusted_adapter(journal, functions)
    finally:
        journal.close()
    assert called[-1] == "contained"
    assert events(directory)[-1]["event"] == "attempt_failed_containment_callback_completed"
    assert all(e["event"] != "attempt_completed" for e in events(directory))
    with pytest.raises(FileExistsError):
        module.DurableAttempt(directory, {}, owner_uid=os.getuid())


def test_crash_after_intent_blocks_resume(tmp_path):
    directory, journal = fixture(tmp_path)
    journal.append("phase_started", {"phase": "migrate097"})
    journal.close()  # simulates process loss before any observed terminal event
    with pytest.raises(FileExistsError):
        module.DurableAttempt(directory, {}, owner_uid=os.getuid())
    assert events(directory)[-1] == {"event": "phase_started", "details": {"phase": "migrate097"}}


def test_containment_failure_is_unknown_not_success(tmp_path):
    directory, journal = fixture(tmp_path)

    def failure():
        raise RuntimeError("synthetic")

    functions = dict.fromkeys(set(module.PHASES) | {"stop_and_preserve_failure"}, failure)
    try:
        with pytest.raises(BaseExceptionGroup):
            module.exercise_trusted_adapter(journal, functions)
    finally:
        journal.close()
    assert events(directory)[-1]["event"] == "containment_unknown"


def test_symlink_marker_never_followed(tmp_path):
    directory, journal = fixture(tmp_path)
    journal.close()
    (directory / "forward097.attempt").unlink()
    victim = tmp_path / "unrelated"
    victim.write_text("unchanged")
    (directory / "forward097.attempt").symlink_to(victim)
    with pytest.raises(FileExistsError):
        module.DurableAttempt(directory, {}, owner_uid=os.getuid())
    assert victim.read_text() == "unchanged"
