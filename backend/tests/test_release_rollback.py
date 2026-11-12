import shlex
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "hostinger-release.sh"


@pytest.mark.parametrize(
    ("path", "operation", "expected_runtime_changed"),
    [
        ("backend/ARCHITECTURE.md", "modify", False),
        ("backend/ARCHITECTURE.md", "add", False),
        ("backend/ARCHITECTURE.md", "remove", False),
        ("backend/tests/test_example.py", "modify", False),
        ("backend/app/ARCHITECTURE.md", "modify", True),
        ("backend/app/main.py", "add", True),
        ("backend/alembic/env.py", "remove", True),
        ("backend/.dockerignore", "modify", True),
        ("docker-compose.prod.yml", "modify", True),
    ],
)
def test_only_backend_documentation_and_tests_skip_runtime_changes(
    tmp_path: Path, path: str, operation: str, expected_runtime_changed: bool
) -> None:
    previous = tmp_path / "previous"
    candidate = tmp_path / "candidate"
    for release in (previous, candidate):
        for directory in ("backend", "nginx", "observability"):
            (release / directory).mkdir(parents=True)
        (release / "docker-compose.prod.yml").write_text("services: {}")
    for release, content in ((previous, "previous"), (candidate, "candidate")):
        if (release == previous and operation == "add") or (
            release == candidate and operation == "remove"
        ):
            continue
        target = release / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    source = SCRIPT.read_text()
    start = source.index("\nsame_backend_runtime() (\n")
    end = source.index("\nfrontend_image=", start)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
previous={shlex.quote(str(previous))}
candidate={shlex.quote(str(candidate))}
generation=1
previous_generation=1
{source[start:end]}
printf '%s\n' "$runtime_changed"
""",
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    assert result.stdout.strip() == str(int(expected_runtime_changed))


@pytest.mark.parametrize(
    "scenario", ["valid", "duplicate-entry", "malformed-entry", "missing-worker", "invalid-digest"]
)
def test_frontend_identity_reads_one_container_and_validates_its_response(
    tmp_path: Path, scenario: str
) -> None:
    asset = "/assets/index-aB2_-9.js"
    index = f'<script type="module" src="{asset}"></script>'.encode()
    if scenario == "duplicate-entry":
        index += b'<script type="module" src="/assets/index-other.js"></script>'
    if scenario == "malformed-entry":
        index = b'<script type="module" src="/assets/index-../entry.js"></script>'
    script = b"console.log('app');\n"
    worker = b"self.addEventListener('install', () => {});\n"
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_bytes(index)
    (tmp_path / asset.lstrip("/")).write_bytes(script)
    if scenario != "missing-worker":
        (tmp_path / "sw.js").write_bytes(worker)

    source = SCRIPT.read_text()
    start = source.index("\nread_frontend_identity() {\n")
    end = source.index("\nruntime_args=()", start)
    invocation = source[start:end].replace("    cd /dist", '    cd "$FRONTEND_DIST"', 1)
    calls = tmp_path / "docker-calls"
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
export FRONTEND_DIST={shlex.quote(str(tmp_path))}
frontend_image=fixture-frontend
die() {{ printf '%s\n' "$1" >&2; exit 1; }}
docker() {{
  [[ "$1 $2 $3 $4 $5 $6 $7" == "run --rm --network none fixture-frontend sh -ec" ]] || return 2
  printf 'readback\n' >> {shlex.quote(str(calls))}
  shift 5
  if [[ {shlex.quote(scenario)} == invalid-digest ]]; then
    printf '%s\n' "broken {asset} {sha256(script).hexdigest()} {sha256(worker).hexdigest()}"
    return
  fi
  "$@"
}}
{invocation}
printf '%s\n' "$expected" "$asset" "$expected_asset" "$expected_worker"
""",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert calls.read_text().splitlines() == ["readback"]
    if scenario == "valid":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            sha256(index).hexdigest(),
            asset,
            sha256(script).hexdigest(),
            sha256(worker).hexdigest(),
        ]
    else:
        assert result.returncode != 0
        assert not result.stdout


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
