"""Fixed host branch sequencing with command boundaries stubbed; not live evidence."""

import subprocess
from pathlib import Path

import pytest

RUNTIME = Path(__file__).resolve().parents[2] / "deploy/forward097-runtime.sh"


@pytest.mark.parametrize("fault", ["none", "migration", "smoke", "process_loss_before_checkpoint"])
def test_actual_shell_forward_branch_order_and_failure(tmp_path, fault):
    trace = tmp_path / "trace"
    script = r"""
set -euo pipefail
source "$1"
state=$2; candidate=$2; previous=$2; project=fixture
current=202605310093; heads=202605310097; runtime_changed=1
sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; run_id=1; ci_attempt=2
deploy_run_id=3; deploy_attempt=4; backend_id=backend-image; frontend_image=frontend-image
schema=202605310093; fault=$3; runtime_attempted=0; frontend_attempted=0
log() { printf '%s\n' "$*" >> "$state/trace"; }
die() { log "ERROR:$*"; exit 7; }
forward_inventory() { log inventory; }
forward_prepare_guard() { log guard_prepared; }
forward_warm_stop() { log "stop:$1"; }
forward_idle() { log worker_idle; }
forward_clients() { echo 0; }
forward_schema() { echo "$schema"; }
forward_data_check() { log data_check; }
forward_verify_schema() { log schema_integrity; }
verify_main() { log verify_main; }
verify_ci() { log verify_ci; }
verify_deploy_run() { log verify_deploy; }
python3() {
 if [[ "$1" == */consume-forward097.py ]]; then log "permit:$2"; else cat >/dev/null; fi
}
sha256sum() { echo 'abcdef  entrypoint'; }
forward_mark() { log "mark:$1"; }
compose() {
 if [[ "$*" == *'alembic upgrade 202605310097'* ]]; then
  log migration; [[ "$fault" != migration ]] || return 9; schema=202605310097
 elif [[ "$*" == *'ps -q backend'* ]]; then echo backend
 elif [[ "$*" == *'celery_worker celery_beat'* ]]; then log workers_started
 else log ingress_reopened; fi
}
forward_compose() { log guarded_candidate_started; }
docker() { echo backend-image; }
publish_frontend() { log frontend_published; }
forward_smoke() { log smoke; [[ "$fault" != smoke ]] || return 8; }
forward_wait_beat() { log beat_ready; }
trap 'rc=$?; if ((rc)); then forward_contain; fi; exit "$rc"' EXIT
forward_release
if [[ "$fault" == process_loss_before_checkpoint ]]; then kill -KILL "$$"; fi
log complete
"""
    result = subprocess.run(
        ["bash", "-c", script, "fixture", str(RUNTIME), str(tmp_path), fault],
        capture_output=True,
        text=True,
    )
    events = trace.read_text().splitlines()
    assert (tmp_path / "forward097.attempt").exists()
    assert events.index("data_check") < events.index("permit:consume") < events.index("migration")
    if fault == "none":
        assert result.returncode == 0, result.stderr
        assert "workers_started" not in events
        assert "ingress_reopened" not in events
        assert "mark:guarded_verification_pending" in events
        assert events.index("schema_integrity") < events.index("guarded_candidate_started")
        assert events[-1] == "complete"
    elif fault == "process_loss_before_checkpoint":
        assert result.returncode == -9
        assert "workers_started" not in events and "ingress_reopened" not in events
        assert events[-1] == "mark:guarded_verification_pending"
    else:
        assert result.returncode != 0
        assert "complete" not in events and "ingress_reopened" not in events
        assert events[-1] == "mark:contained_failure"
    assert not any("backup" in e or "downgrade" in e for e in events)


def test_root_helper_binding_is_exact_and_before_staging():
    import hashlib

    host = (RUNTIME.parent / "hostinger-release.sh").read_text()
    for name in ("forward097-runtime.sh", "forward_release_contract.py", "consume-forward097.py"):
        assert hashlib.sha256((RUNTIME.parent / name).read_bytes()).hexdigest() in host
    assert host.index("source /usr/local/lib/garrison-release/forward097-runtime.sh") < host.index(
        "candidate=$(mktemp"
    )
    assert "if (( runtime_changed && ! forward097 )); then" in host
    assert "if (( ! pinned && ! forward097 ))" in host


@pytest.mark.parametrize("state", ["", "false", "false dead", "ERROR", "true restarting"])
def test_stop_rejects_unknown_state(tmp_path, state):
    script = r"""set -euo pipefail
source "$1"
project=fixture
docker() {
 if [[ "$1" == ps ]]; then echo fixture-id
 elif [[ "$3" == *State* ]]; then [[ "$STATE" != ERROR ]] || return 9; echo "$STATE"
 else return 9; fi
}
forward_warm_stop backend
"""
    import os

    result = subprocess.run(
        ["bash", "-c", script, "test", str(RUNTIME)],
        env={**os.environ, "STATE": state},
        capture_output=True,
    )
    assert result.returncode != 0


def test_checkpoint_precedes_reopening_and_all_mode_interlock():
    host = (RUNTIME.parent / "hostinger-release.sh").read_text()
    assert host.index('mv -Tf "$state/.current-next"') < host.index("candidate/'FORWARD_VERIFIED'")
    assert host.index("candidate/'FORWARD_VERIFIED'") < host.index("  forward_reopen\n")
    release = RUNTIME.read_text().split("forward_release() {", 1)[1]
    assert "forward_reopen" not in release.split("# Called only", 1)[0]


def test_exact_reopen_process_loss_retains_durable_committed_identity(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "FORWARD_VERIFIED").write_text("verified")
    (tmp_path / "current").symlink_to(candidate)
    script = r"""set -euo pipefail
source "$1"
state=$2; candidate=$2/candidate
sha=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; run_id=1; ci_attempt=2
deploy_run_id=3; deploy_attempt=4; backend_id=exact-image
forward_wait_beat() { :; }
forward_inventory() { :; }
forward_smoke() { :; }
forward_mark() { printf '%s\n' "$1" >> "$state/trace"; }
readlink() { printf '%s\n' "$candidate"; }
docker() {
 if [[ "$1" == exec ]]; then echo '{"fixture":{"ok":"pong"}}'
 else echo 'exact-image true'; fi
}
compose() {
 if [[ "$*" == *'ps -q'* ]]; then echo writer
 elif [[ "$*" == *'150 nginx' ]]; then
  touch "$state/traffic-open"
  kill -KILL "$$"
 fi
}
forward_reopen
"""
    result = subprocess.run(
        ["bash", "-c", script, "test", str(RUNTIME), str(tmp_path)], capture_output=True
    )
    assert result.returncode == -9, result.stderr
    import json

    commit = json.loads((tmp_path / "forward097.reopen-commit").read_text())
    assert commit["sha"] == "a" * 40 and commit["ci_attempt"] == "2"
    assert commit["state"] == "verified-serving-committed"
    assert (tmp_path / "traffic-open").exists()
    assert not (candidate / "DEPLOYED").exists()
    assert "ingress_reopened" not in (tmp_path / "trace").read_text()
