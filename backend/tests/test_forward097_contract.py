import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "deploy/forward_release_contract.py"
spec = importlib.util.spec_from_file_location("forward_release_contract", FILE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    now = int(time.time())
    args = dict(
        sha="a" * 40, ci_run=1, ci_attempt=1, deploy_run=2, attempt=1, entrypoint_sha256="b" * 64
    )
    permit = dict(
        args,
        mode="forward-only-093-to-097",
        source="202605310093",
        target="202605310097",
        not_before=now - 1,
        expires=now + 60,
    )
    return args, permit, now


@pytest.mark.parametrize(
    "key,value",
    [
        ("sha", "c" * 40),
        ("ci_run", 8),
        ("ci_attempt", 2),
        ("deploy_run", 9),
        ("attempt", 2),
        ("source", "202605310094"),
        ("target", "202605310098"),
        ("entrypoint_sha256", "c" * 64),
        ("mode", "technical-checks-v1"),
        ("expires", 1),
        ("ci_run", True),
    ],
)
def test_permit_identity_and_expiry_reject(key, value):
    args, permit, now = fixture()
    permit[key] = value
    with pytest.raises(ValueError):
        module.validate_permit(json.dumps(permit).encode(), now=now, **args)


def test_valid_permit_and_excessive_window():
    args, permit, now = fixture()
    assert module.validate_permit(json.dumps(permit).encode(), now=now, **args) == permit
    permit["expires"] = now + 2000
    with pytest.raises(ValueError):
        module.validate_permit(json.dumps(permit).encode(), now=now, **args)


def test_atomic_one_use_and_replay(tmp_path):
    args, permit, _ = fixture()
    directory = tmp_path / "operator" / "permits"
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "forward097.permit"
    path.write_text(json.dumps(permit))
    path.chmod(0o600)
    assert module.consume_permit(directory, owner_uid=os.getuid(), **args) == permit
    assert (directory / "forward097.used").read_text() == json.dumps(permit)
    path.write_text(json.dumps(permit))
    path.chmod(0o600)
    with pytest.raises(FileExistsError):
        module.consume_permit(directory, owner_uid=os.getuid(), **args)


def test_writable_parent_denied(tmp_path):
    directory = tmp_path / "operator" / "permits"
    directory.mkdir(parents=True)
    directory.parent.chmod(0o777)
    args, _, _ = fixture()
    with pytest.raises(ValueError):
        module.consume_permit(directory, owner_uid=os.getuid(), **args)


def test_manual_only_host_path_and_fail_closed_activation():
    root = FILE.parent.parent
    workflow = (root / ".github/workflows/deploy.yml").read_text()
    host = (root / "deploy/hostinger-release.sh").read_text()
    assert (
        '"$GITHUB_EVENT_NAME" == workflow_dispatch && "$PINNED_NO_BACKUP_093" != true' in workflow
    )
    assert '"$expected_main" "$((pinned || forward097))"' in host
    assert host.index("Forward runtime installation is not protected") < host.index(
        "candidate=$(mktemp"
    )
    assert '[[ "$current" == 202605310061 && "$heads" == 202605310093' in host
    assert "Pending database migrations require the reviewed maintenance procedure." in host
    assert "python scripts/backup.py --target all --skip-retention" in host
    assert 'sha" == 0d581001bd294f79a47021c7e30f75a1bf291d2a' in host


@pytest.mark.parametrize("event,accepted", [("workflow_run", False), ("workflow_dispatch", True)])
def test_host_rejects_automatic_forward_mode(event, accepted):
    import shlex
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("\nverify_deploy_run() {\n")
    end = source.index("\nif (( pinned )); then\n  consume_pinned_exception", start)
    sha = "a" * 40
    run = dict(
        id=456,
        run_attempt=1,
        path=".github/workflows/deploy.yml",
        status="in_progress",
        head_branch="main",
        head_repository={"full_name": "nirzaf/garrison-investments"},
        event=event,
        head_sha=sha,
    )
    setup = (
        "set -euo pipefail; deploy_run_id=456; deploy_attempt=1; "
        "repository=nirzaf/garrison-investments; "
        f"expected_main={sha}; pinned=0; forward097=1; "
        f"github() {{ printf '%s' {shlex.quote(json.dumps(run))}; }};"
    )
    result = subprocess.run(
        ["bash", "-c", setup + source[start:end] + "\nverify_deploy_run"],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is accepted


def test_all_modes_interlocked_before_schema_fast_path(tmp_path):
    import subprocess

    text = (FILE.parent / "hostinger-release.sh").read_text()
    start = text.index("assert_forward_maintenance_clear() {")
    end = text.index("\n}\n", start) + 3
    function = text[start:end]
    assert text.index("assert_forward_maintenance_clear\n") < text.index("if (( pinned )); then")
    for mode in ("technical-checks-v1", "pinned-no-backup-093", "forward-only-093-to-097"):
        command = (f'die() {{ exit 71; }}; state="$1"; release_mode="$2"; {function}\n'
                   "assert_forward_maintenance_clear")
        assert (
            subprocess.run(["bash", "-c", command, "fixture", str(tmp_path), mode]).returncode == 0
        )
        (tmp_path / "forward097.attempt").write_text("migration-intent: process disappeared")
        assert (
            subprocess.run(["bash", "-c", command, "fixture", str(tmp_path), mode]).returncode == 71
        )
        (tmp_path / "forward097.attempt").unlink()
