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
    assert (
        "echo incident; elif (( pinned || forward097 || postgres19_maintenance )); then echo manual"
        in host
    )
    assert host.index("Forward runtime installation is not protected") < host.index(
        "candidate=$(mktemp"
    )
    assert '[[ "$current" == 202605310061 && "$heads" == 202605310093' in host
    assert "Pending database migrations require the reviewed maintenance procedure." in host
    assert "python -m scripts.backup --target all --skip-retention" in host
    assert "consume_postgres19_maintenance_permit" in host
    assert "postgres19-maintenance.started" in host
    assert "validate_compose_transition" in host
    assert '"$heads" == 202605310098' in host
    assert "garrison-portal_pgdata19" in host
    assert "Maintenance actual end Asia/Qatar" in host
    assert "postgres19-maintenance" in workflow
    assert (
        'if release_mode in ("postgres19-maintenance", "postgres19-maintenance-retry"):'
        in host
    )
    assert '"$PINNED_NO_BACKUP_093" != true' in workflow
    assert '"$FORWARD_ONLY_093_TO_097" != true' in workflow
    assert '"$INCIDENT_REPLACEMENT" != true' in workflow
    assert 'sha" == 0d581001bd294f79a47021c7e30f75a1bf291d2a' in host
    assert "RELEASE_SHA=65308a2af263cd59e90276b3a771d4ed6ecbf842" in workflow
    assert 'CI_RUN_ID" == 44734573582' in workflow
    assert "compare/65308a2af263cd59e90276b3a771d4ed6ecbf842...$expected_main" in host
    reconciliation = root / "deploy/forward097_reconcile.py"
    assert "forward097.reconciled.json" in reconciliation.read_text()
    assert hashlib.sha256(reconciliation.read_bytes()).hexdigest() in host


@pytest.mark.parametrize(
    ("merge_base_sha", "accepted"),
    [
        ("65308a2af263cd59e90276b3a771d4ed6ecbf842", True),
        ("different-commit", False),
    ],
)
def test_incident_ancestry_guard_uses_github_compare_merge_base_field(
    merge_base_sha: str, accepted: bool
) -> None:
    import subprocess
    import sys

    source = (FILE.parent / "hostinger-release.sh").read_text()
    compare_start = source.index('github "compare/65308a2af263cd59e90276b3a771d4ed6ecbf842...')
    python_start = source.index("| python3 -c '\n", compare_start) + len("| python3 -c '\n")
    python_end = source.index("\n'\n", python_start)
    validator = source[python_start:python_end]
    response = {
        "status": "ahead",
        "base_commit": {"sha": "65308a2af263cd59e90276b3a771d4ed6ecbf842"},
        "merge_base_commit": {"sha": merge_base_sha},
    }

    result = subprocess.run(
        [sys.executable, "-c", validator],
        input=json.dumps(response),
        capture_output=True,
        text=True,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "no longer an ancestor" in result.stderr


def test_legacy_backup_contract_is_limited_to_incident_replacement() -> None:
    host = (FILE.parent / "hostinger-release.sh").read_text()
    start = host.index('if release_mode == "incident-replacement":')
    end = host.index("\n\nmounted_files_by_target", start)
    compatibility_branch = host[start:end]
    import_header = host[
        host.index('sys.path.insert(0, str(candidate / "deploy"))') : start
    ]
    assert "validate_backup_secret_configuration" not in import_header
    assert '"BACKUP_ENCRYPTION_PASSWORD" not in env_values' in compatibility_branch
    assert '"BACKUP_ENCRYPTION_KEY_HOST_FILE" in env_values' in compatibility_branch
    assert "validate_backup_secret_configuration" in compatibility_branch
    assert '"$release_mode" <<\'PY\'' in host

    legacy_environment = {
        "BACKUP_ENCRYPTION_PASSWORD": "synthetic-only",
        "LOG_PURGE_ENABLED": "false",
    }
    exec(  # noqa: S102 - execute the extracted release guard as its regression test.
        compatibility_branch,
        {"release_mode": "incident-replacement", "env_values": legacy_environment},
    )


def test_incident_replacement_overrides_the_recovery_archive_proxy() -> None:
    host = (FILE.parent / "hostinger-release.sh").read_text()
    assert (
        "nginx:1.30.7-alpine@sha256:"
        "caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3"
    ) in host
    assert 'incident_nginx_override="$candidate/.incident-nginx-override.yml"' in host
    assert 'compose_files+=(-f "$proxy_override")' in host
    assert "nginx_test_override_file=$(mktemp \"$state/.nginx-test-override.XXXXXX\")" in host
    assert 'extra_hosts:\\n      - "backend-proxy:%s"\\n      - "grafana:%s"' in host
    assert 'compose "$candidate" run --rm --no-deps -T nginx nginx -t' in host
    assert "nginx version: nginx/1.30.7" in host
    assert "The previous Nginx container is still present after patched proxy activation." in host


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


@pytest.mark.parametrize(
    "scenario",
    [
        "valid",
        "expired",
        "future",
        "too-long",
        "wrong-run",
        "wrong-sha",
        "replay",
        "missing-start",
        "wrong-start-sha",
        "future-start",
    ],
)
def test_postgres19_maintenance_permit_is_one_use_sha_bound_and_time_bounded(
    scenario: str, tmp_path: Path
) -> None:
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("consume_postgres19_maintenance_permit() {")
    end = source.index("github() {", start)
    permit = tmp_path / "postgres19-maintenance.permit"
    started = tmp_path / "postgres19-maintenance.started"
    used = tmp_path / "postgres19-maintenance.used"
    start_time, end_time = 1_800_000_000, 1_800_000_300
    run, sha = "34", "a" * 40
    if scenario == "expired":
        end_time = 1_800_000_100
    elif scenario == "future":
        start_time = 1_800_000_200
    elif scenario == "too-long":
        end_time = 1_800_008_000
    elif scenario == "wrong-run":
        run = "35"
    elif scenario == "wrong-sha":
        sha = "b" * 40
    elif scenario == "replay":
        used.touch()
    permit.write_text(f"{run} {sha} {start_time} {end_time}\n")
    permit.chmod(0o600)
    if scenario != "missing-start":
        started_sha = "b" * 40 if scenario == "wrong-start-sha" else "a" * 40
        started_at = 1_800_000_200 if scenario == "future-start" else 1_800_000_050
        started.write_text(f"{started_sha} 34 {started_at}\n")
        started.chmod(0o600)
    result = subprocess.run(
        [
            "bash",
            "-eu",
            "-c",
            """
die() { echo "$1" >&2; exit 1; }
date() { echo 1800000100; }
stat() { echo 600; }
mv() { shift 2; command mv "$@"; }
state=$1
project=garrison-portal
run_id=34
sha=$(printf 'a%.0s' {1..40})
postgres19_retry=0
"""
            + source[start:end]
            + "\nconsume_postgres19_maintenance_permit\nassert_postgres19_window\n",
            "permit-test",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (scenario == "valid"), result.stderr
    assert permit.exists() == (scenario != "valid")
    assert used.exists() == (scenario in {"valid", "replay"})


@pytest.mark.parametrize(
    ("scenario", "valid"),
    [
        ("valid", True),
        ("prior-run-success", False),
        ("bad-evidence", False),
        ("active-writers", False),
        ("changed-current", False),
        ("expired", False),
        ("too-long", False),
        ("extra-field", False),
        ("archive-exists", False),
        ("replay", False),
    ],
)
def test_postgres19_retry_authorization_is_single_use_and_failure_bound(
    scenario: str, valid: bool, tmp_path: Path
) -> None:
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("consume_postgres19_maintenance_retry_followup_authorization() {")
    end = source.index("github() {", start)
    state = tmp_path
    old_sha = "b" * 40
    current_sha = "c" * 40
    new_sha = "a" * 40
    old_start, retry_start, now, end_time = (
        1_799_999_900,
        1_799_999_950,
        1_800_000_100,
        1_800_000_300,
    )
    if scenario == "expired":
        end_time = 1_800_000_050
    elif scenario == "too-long":
        end_time = 1_800_008_000
    (state / "current").mkdir()
    observed_current_sha = "d" * 40 if scenario == "changed-current" else current_sha
    (state / "current" / "DEPLOYED").write_text(f"Commit: {observed_current_sha}\n")
    prior_used = state / "postgres19-maintenance.used"
    prior_used.write_text(f"33 {old_sha} {old_start} {end_time}\n")
    prior_used.chmod(0o600)
    original_started = state / "postgres19-maintenance.started"
    original_started.write_text(f"{old_sha} 33 {retry_start}\n")
    original_started.chmod(0o600)
    evidence = state / "postgres19-maintenance.retry-evidence"
    evidence.write_text("Verified pre-activation Nginx configuration test failure.\n")
    evidence.chmod(0o600)
    evidence_sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
    if scenario == "bad-evidence":
        evidence_sha = "d" * 64
    authorization = state / "postgres19-maintenance.retry.permit"
    authorization.write_text(
        f"34 {new_sha} {retry_start} {end_time} 12 33 {old_sha} "
        f"{current_sha} {evidence_sha}"
        f" {'unexpected' if scenario == 'extra-field' else ''}\n"
    )
    authorization.chmod(0o600)
    if scenario == "archive-exists":
        (state / "postgres19-maintenance.retry.authorization").touch()
    if scenario == "replay":
        (state / "postgres19-maintenance.retry.used").touch()
    prior_conclusion = "success" if scenario == "prior-run-success" else "failure"

    script = f"""
die() {{ echo "$1" >&2; exit 1; }}
date() {{ if [[ "$*" == *%s* ]]; then echo {now}; else echo 2026-11-22T08:00:00Z; fi; }}
stat() {{ echo 600; }}
mv() {{ shift 2; command mv "$@"; }}
github() {{
  cat <<'JSON'
{{"id":12,"workflow_id":277757082,"head_sha":"{old_sha}","event":"workflow_dispatch","status":"completed","conclusion":"{prior_conclusion}"}}
JSON
}}
docker() {{
  if [[ {scenario!r} == active-writers ]]; then
    echo 'backend postgres redis'
  else
    echo 'postgres redis minio loki alloy'
  fi
}}
state=$1
project=garrison-portal
run_id=34
sha={new_sha}
deploy_run_id=56
deploy_attempt=1
postgres19_retry=1
""" + source[start:end] + """
consume_postgres19_maintenance_permit
printf '%s %s %s %s\\n' \\
  "$postgres19_start" "$postgres19_end" "$postgres19_retry_run" "$postgres19_retry_evidence_sha"
"""
    result = subprocess.run(
        ["bash", "-eu", "-c", script, "retry-test", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == valid, result.stderr
    assert authorization.exists() is (not valid)
    assert (state / "postgres19-maintenance.retry.used").exists() is valid or scenario == "replay"
    if valid:
        consumed = (state / "postgres19-maintenance.retry.used").read_text()
        assert "Deployment run: 56" in consumed
        assert "Deployment attempt: 1" in consumed
        assert str(retry_start) in result.stdout


@pytest.mark.parametrize(
    ("scenario", "valid"),
    [
        ("valid", True),
        ("prior-run-success", False),
        ("bad-evidence", False),
        ("active-writers", False),
        ("changed-current", False),
        ("expired", False),
        ("too-long", False),
        ("window-not-started", False),
        ("bad-history", False),
        ("extra-field", False),
        ("replay", False),
    ],
)
def test_postgres19_followup_retry_preserves_and_chains_failed_retry(
    scenario: str, valid: bool, tmp_path: Path
) -> None:
    import subprocess

    source = (FILE.parent / "hostinger-release.sh").read_text()
    start = source.index("consume_postgres19_maintenance_retry_followup_authorization() {")
    end = source.index("github() {", start)
    state = tmp_path
    original_sha = "b" * 40
    current_sha = "c" * 40
    first_retry_sha = "d" * 40
    new_sha = "a" * 40
    original_start, first_retry_start, original_end = 1_800_000_000, 1_800_000_010, 1_800_000_300
    followup_start, now, followup_end = 1_800_000_400, 1_800_000_500, 1_800_000_600
    if scenario == "expired":
        followup_end = now
    elif scenario == "too-long":
        followup_end = followup_start + 7201
    elif scenario == "window-not-started":
        followup_start = now + 1

    (state / "current").mkdir()
    receipt_sha = "e" * 40 if scenario == "changed-current" else current_sha
    (state / "current" / "DEPLOYED").write_text(f"Commit: {receipt_sha}\n")
    original_used = state / "postgres19-maintenance.used"
    original_used.write_text(f"33 {original_sha} {original_start} {original_end}\n")
    original_used.chmod(0o600)
    original_started = state / "postgres19-maintenance.started"
    original_started.write_text(f"{original_sha} 33 {original_start + 5}\n")
    original_started.chmod(0o600)

    first_evidence = state / "postgres19-maintenance.retry-evidence"
    first_evidence.write_text("Verified pre-activation Nginx test failure.\n")
    first_evidence.chmod(0o600)
    first_evidence_sha = hashlib.sha256(first_evidence.read_bytes()).hexdigest()
    first_permit_line = (
        f"34 {first_retry_sha} {first_retry_start} {original_end} 12 33 "
        f"{original_sha} {current_sha} {first_evidence_sha}"
    )
    first_authorization = state / "postgres19-maintenance.retry.authorization"
    first_authorization.write_text(first_permit_line + "\n")
    first_authorization.chmod(0o600)
    first_used = state / "postgres19-maintenance.retry.used"
    first_used.write_text(
        first_permit_line
        + "\nDeployment run: 56\nDeployment attempt: 1\nConsumed UTC: 2026-11-22T08:51:20Z\n"
    )
    first_used.chmod(0o600)

    followup_evidence = state / "postgres19-maintenance.retry-followup-evidence"
    followup_evidence.write_text(
        "Prior follow-up deployment run: 56\n"
        "Disposition: pre-activation failure; production receipt unchanged\n"
        f"Previous receipt SHA: {current_sha}\n"
        f"Runner log SHA-256: {'f' * 64}\n"
    )
    followup_evidence.chmod(0o600)
    followup_evidence_sha = hashlib.sha256(followup_evidence.read_bytes()).hexdigest()
    if scenario == "bad-evidence":
        followup_evidence_sha = "e" * 64
    followup_permit = state / "postgres19-maintenance.retry-followup.permit"
    followup_permit.write_text(
        f"35 {new_sha} {followup_start} {followup_end} 56 34 {first_retry_sha} "
        f"{current_sha} {followup_evidence_sha}"
        f" {'unexpected' if scenario == 'extra-field' else ''}\n"
    )
    followup_permit.chmod(0o600)
    if scenario == "replay":
        (state / "postgres19-maintenance.retry-followup.used").touch()
    if scenario == "bad-history":
        first_authorization.write_text("invalid preserved retry history\n")

    prior_conclusion = "success" if scenario == "prior-run-success" else "failure"
    script = f"""
die() {{ echo "$1" >&2; exit 1; }}
date() {{ if [[ "$*" == *%s* ]]; then echo {now}; else echo 2026-11-22T09:15:00Z; fi; }}
stat() {{ echo 600; }}
mv() {{ shift 2; command mv "$@"; }}
github() {{
  cat <<'JSON'
{{"id":56,"workflow_id":277757082,"head_sha":"{first_retry_sha}","event":"workflow_dispatch","status":"completed","conclusion":"{prior_conclusion}"}}
JSON
}}
docker() {{
  if [[ {scenario!r} == active-writers ]]; then echo 'backend postgres redis';
  else echo 'postgres redis minio loki alloy'; fi
}}
state=$1
project=garrison-portal
run_id=35
sha={new_sha}
deploy_run_id=57
deploy_attempt=1
postgres19_retry=1
""" + source[start:end] + """
consume_postgres19_maintenance_permit
printf '%s %s %s %s\\n' \\
  "$postgres19_start" "$postgres19_end" "$postgres19_retry_run" "$postgres19_retry_evidence_sha"
"""
    result = subprocess.run(
        ["bash", "-eu", "-c", script, "retry-followup-test", str(state)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == valid, result.stderr
    assert followup_permit.exists() is (not valid)
    assert (state / "postgres19-maintenance.retry-followup.authorization").exists() is valid
    assert (state / "postgres19-maintenance.retry-followup.used").exists() is valid or (
        scenario == "replay"
    )
    if valid:
        consumed = (state / "postgres19-maintenance.retry-followup.used").read_text()
        assert "Deployment run: 57" in consumed
        assert str(followup_start) in consumed.splitlines()[0]
        assert str(original_start + 5) in result.stdout
