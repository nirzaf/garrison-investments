import shlex
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "hostinger-release.sh"


@pytest.mark.parametrize(
    ("previous_generation", "old_heads", "frontend_available", "expected_actions"),
    [
        ("1", "current-head", True, ["runtime previous", "frontend previous-frontend"]),
        ("", "current-head", True, ["stop nginx celery_beat celery_worker backend"]),
        ("1", "old-head", True, ["stop nginx celery_beat celery_worker backend"]),
        ("1", "current-head", False, ["stop nginx celery_beat celery_worker backend"]),
    ],
)
def test_failed_activation_only_restores_compatible_release(
    tmp_path: Path,
    previous_generation: str,
    old_heads: str,
    frontend_available: bool,
    expected_actions: list[str],
) -> None:
    previous = tmp_path / "previous"
    previous.mkdir()
    (previous / ".images.env").write_text(
        "GARRISON_BACKEND_IMAGE=previous-backend\nGARRISON_FRONTEND_IMAGE=previous-frontend\n"
    )
    candidate = tmp_path / "candidate"
    candidate.mkdir()

    # Exercise the installed script's decision and EXIT trap without host access.
    source = SCRIPT.read_text()
    start = source.index("\nrollback_compatible=0\n")
    end = source.index("\ntrap 'exit 130' INT\n", start)
    result = subprocess.run(
        [
            "bash",
            "-c",
            rf"""
set -euo pipefail
previous={shlex.quote(str(previous))}
candidate={shlex.quote(str(candidate))}
generation=1
previous_generation={shlex.quote(previous_generation)}
current=current-head
sha=synthetic-commit
run_id=123
image_heads() {{ printf '%s\n' {shlex.quote(old_heads)}; }}
docker() {{ {"true" if frontend_available else "false"}; }}
apply_runtime() {{ printf 'runtime %s\n' "${{1##*/}}"; }}
publish_frontend() {{ printf 'frontend %s\n' "$1"; }}
compose() {{ shift; printf '%s\n' "$*"; }}
{source[start:end]}
runtime_attempted=1
frontend_attempted=1
exit 23
""",
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 23
    assert result.stdout.splitlines() == expected_actions
    receipt = candidate / "ACTIVATION_FAILED"
    if expected_actions[0].startswith("stop "):
        assert "recover forward" in result.stderr
        assert "Exit: 23" in receipt.read_text()
    else:
        assert "Restoring the previous compatible application release" in result.stderr
        assert not receipt.exists()


@pytest.mark.parametrize("protocol", [[], ["rollback-v2"]])
def test_legacy_workflow_invocation_is_rejected_before_token_read(protocol: list[str]) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "123", "a" * 40, *protocol],
        input="",
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert "rollback-v2 and release-contract-v1" in result.stderr


def test_missing_installed_verifier_blocks_candidate_download(tmp_path: Path) -> None:
    source = SCRIPT.read_text()
    start = source.index("\nverify_authorization() {\n")
    end = source.index('\ngithub "actions/runs/', start)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
verifier={shlex.quote(str(tmp_path / "missing.py"))}
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
{source[start:end]}
verify_authorization
printf 'Candidate activation reached\\n'
""",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert "root-installed release verifier is unavailable" in result.stderr
    assert not result.stdout
    authorization = source.index("authorization=$(verify_authorization)")
    assert authorization < source.index('github "tarball/$sha"')


def test_unhealthy_runtime_cannot_be_masked_by_nginx_reload() -> None:
    source = SCRIPT.read_text()
    start = source.index("\napply_runtime() {\n")
    end = source.index("\nrollback_compatible=0\n", start)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
project=disposable
compose() {{ return 42; }}
docker() {{ echo 'Unexpected Nginx reload'; }}
{source[start:end]}
apply_runtime previous || exit "$?"
""",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 42
    assert not result.stdout
