import hashlib
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
    assert "echo incident; elif (( pinned || forward097 )); then echo manual" in host
    assert host.index("Forward runtime installation is not protected") < host.index(
        "candidate=$(mktemp"
    )
    assert '[[ "$current" == 202605310061 && "$heads" == 202605310093' in host
    assert "Pending database migrations require the reviewed maintenance procedure." in host
    assert "python scripts/backup.py --target all --skip-retention" in host
    assert 'sha" == 0d581001bd294f79a47021c7e30f75a1bf291d2a' in host
    assert "RELEASE_SHA=65308a2af263cd59e90276b3a771d4ed6ecbf842" in workflow
    assert 'CI_RUN_ID" == 44734573582' in workflow
    assert "compare/65308a2af263cd59e90276b3a771d4ed6ecbf842...$expected_main" in host
    reconciliation = root / "deploy/forward097_reconcile.py"
    assert "forward097.reconciled.json" in reconciliation.read_text()
    assert hashlib.sha256(reconciliation.read_bytes()).hexdigest() in host


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
        f"expected_main={sha}; pinned=0; forward097=1; incident_replacement=0; "
        f"github() {{ printf '%s' {shlex.quote(json.dumps(run))}; }};"
    )
    result = subprocess.run(
        ["bash", "-c", setup + source[start:end] + "\nverify_deploy_run"],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is accepted


def test_incident_dispatch_uses_the_dispatch_main_sha_not_the_older_release_sha():
    import shlex
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("\nverify_deploy_run() {\n")
    end = source.index("\nif (( pinned )); then\n  consume_pinned_exception", start)
    main_sha = "b" * 40
    deployment = {
        "id": 456,
        "run_attempt": 1,
        "path": ".github/workflows/deploy.yml",
        "status": "in_progress",
        "head_branch": "main",
        "head_repository": {"full_name": "nirzaf/garrison-investments"},
        "event": "workflow_dispatch",
        "head_sha": main_sha,
    }
    setup = (
        "set -euo pipefail; deploy_run_id=456; deploy_attempt=1; "
        "repository=nirzaf/garrison-investments; "
        f"expected_main={'65308a2af263cd59e90276b3a771d4ed6ecbf842'}; "
        "incident_replacement=1; pinned=0; forward097=0; "
        f"github() {{ printf '%s' {shlex.quote(json.dumps(deployment))}; }};"
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            setup
            + source[start:end]
            + "\ndeployment_main_sha=$(verify_deploy_run); echo $deployment_main_sha",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == main_sha

    deployment["event"] = "workflow_run"
    blocked = setup.replace(
        shlex.quote(json.dumps({**deployment, "event": "workflow_dispatch"})),
        shlex.quote(json.dumps(deployment)),
    )
    result = subprocess.run(
        ["bash", "-c", blocked + source[start:end] + "\nverify_deploy_run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "second_page_environment,accepted", [("Preview", True), ("Production", False)]
)
def test_incident_predecessor_deployment_check_paginates(second_page_environment, accepted):
    import shlex
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("\nverify_no_predecessor_production_deployment() {\n") + 1
    end = source.index("\n}\n", start) + 3
    function = source[start:end]
    page_one = json.dumps([{"environment": "Preview"}] * 100)
    page_two = json.dumps([{"environment": second_page_environment}])
    setup = (
        "set -euo pipefail; "
        f"page_one={shlex.quote(page_one)}; page_two={shlex.quote(page_two)}; "
        "die() { exit 71; }; "
        "github() { printf '%s\\n' \"$1\" >&2; "
        'case "$1" in *page=1) printf \'%s\' "$page_one";; '
        "*page=2) printf '%s' \"$page_two\";; *) exit 72;; esac; }; "
    )
    result = subprocess.run(
        ["bash", "-c", setup + function + "\nverify_no_predecessor_production_deployment"],
        capture_output=True,
        text=True,
    )
    assert (result.returncode == 0) is accepted
    assert result.stderr.count("deployments?sha=") == 2


@pytest.mark.parametrize(
    "run_id,sha",
    [
        (44734573581, "65308a2af263cd59e90276b3a771d4ed6ecbf842"),
        (44734573582, "65308a2af263cd59e90276b3a771d4ed6ecbf843"),
    ],
)
def test_incident_replacement_refuses_any_candidate_other_than_green_65308a2(run_id, sha):
    import subprocess

    script = FILE.parent / "hostinger-release.sh"
    result = subprocess.run(
        ["bash", str(script), str(run_id), sha, "rollback-v2", "incident-replacement"],
        input="",
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "pinned to the previously verified green 65308a2" in result.stderr


def test_marker_is_preserved_and_only_verified_reconciliation_reopens_normal_deploys(tmp_path):
    import subprocess

    text = (FILE.parent / "hostinger-release.sh").read_text()
    start = text.index("assert_forward_maintenance_clear() {")
    end = text.index("\n}\n", start) + 3
    function = text[start:end]
    assert text.index("assert_forward_maintenance_clear\n") < text.index("if (( pinned )); then")
    command = (
        "set -euo pipefail; die() { exit 71; }; "
        'state="$1"; release_mode="$2"; incident_replacement=0; '
        "forward_reconcile_tool=/root/helper; "
        "verify_forward_reconcile_tool() { :; }; "
        'python3() { if [[ "$2" == verify && '
        '-e "$state/forward097.reconciled.json" ]]; then return 0; else return 1; fi; }; '
        f"{function}\nassert_forward_maintenance_clear"
    )
    marker = tmp_path / "forward097.attempt"
    marker.write_text("migration-intent: process disappeared")
    for mode in ("technical-checks-v1", "pinned-no-backup-093", "forward-only-093-to-097"):
        result = subprocess.run(["bash", "-c", command, "fixture", str(tmp_path), mode])
        assert result.returncode == 71
        assert marker.read_text() == "migration-intent: process disappeared"

    receipt = tmp_path / "forward097.reconciled.json"
    receipt.write_text('{"verified": true}\n')
    result = subprocess.run(
        ["bash", "-c", command, "fixture", str(tmp_path), "technical-checks-v1"]
    )
    assert result.returncode == 0
    assert marker.read_text() == "migration-intent: process disappeared"

    incident_command = command.replace("incident_replacement=0", "incident_replacement=1")
    result = subprocess.run(
        ["bash", "-c", incident_command, "fixture", str(tmp_path), "incident-replacement"]
    )
    assert result.returncode == 71
    assert marker.read_text() == "migration-intent: process disappeared"
