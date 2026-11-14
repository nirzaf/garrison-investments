import io
import json
import shlex
import subprocess
import tarfile
from hashlib import sha256
from pathlib import Path

import pytest

from scripts.release_contract import deployment_receipt_fields, utc, verify_host_deployment_receipt

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "hostinger-release.sh"


@pytest.mark.parametrize("job_attempt", [2, 3])
def test_deployment_receipt_records_only_the_ci_attempt_that_passed(
    tmp_path: Path, job_attempt: int
) -> None:
    source = SCRIPT.read_text()
    start = source.index("\nverify_ci() {\n")
    end = source.index('\ngithub "actions/runs/$deploy_run_id', start)
    receipt_start = source.index("\nprintf 'Status: Deployed")
    receipt_end = source.index("\nln -sfn", receipt_start)
    sha = "a" * 40
    repository = "nirzaf/garrison-investments"
    run = json.dumps({
        "id": 123, "path": ".github/workflows/ci.yml", "event": "push",
        "status": "completed", "conclusion": "success", "head_branch": "main",
        "head_repository": {"full_name": repository}, "head_sha": sha, "run_attempt": 2,
    })
    names = (
        "Backend lint and types", "Frontend lint, types, tests and build",
        "Compose files are valid",
        "Backend tests (1/2)", "Backend tests (2/2)",
        "Browser regressions (1/2)", "Browser regressions (2/2)",
    )
    jobs = json.dumps({
        "total_count": len(names),
        "jobs": [
            {"name": name, "run_id": 123, "head_sha": sha, "run_attempt": job_attempt,
             "status": "completed", "conclusion": "success"}
            for name in names
        ],
    })
    result = subprocess.run(
        ["bash", "-c", f"""
set -euo pipefail
run_id=123
sha={sha}
repository={repository}
candidate={shlex.quote(str(tmp_path))}
deploy_run_id=456
deploy_attempt=1
asset=/assets/index.js
expected_asset=asset-digest
expected_worker=worker-digest
backend_id=backend-image
frontend_id=frontend-image
current=schema-head
predeploy_digest=fixture-predeploy-digest
predeploy_manifest_digest=fixture-predeploy-manifest-digest
github() {{
  case "$1" in
    actions/runs/123) printf '%s\n' {shlex.quote(run)} ;;
    'actions/runs/123/attempts/2/jobs?per_page=100') printf '%s\n' {shlex.quote(jobs)} ;;
    *) return 2 ;;
  esac
}}
{source[start:end]}
{source[receipt_start:receipt_end]}
"""],
        capture_output=True,
        check=False,
        text=True,
    )
    receipt = tmp_path / "DEPLOYED"
    if job_attempt == 2:
        assert result.returncode == 0, result.stderr
        assert receipt.read_text().splitlines()[1:6] == [
            f"Commit: {sha}",
            "CI run: 123",
            "CI attempt: 2",
            "Deploy run: 456",
            "Deploy attempt: 1",
        ]
    else:
        assert result.returncode != 0
        assert not receipt.exists()
        assert "missing a passed required job" in result.stderr


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
        (release / ".env").write_text("LOG_PURGE_ENABLED=false\n")
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
    end = source.index("\npublish_frontend()", start)
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
ci_attempt=2
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
        assert "CI attempt: 2" in receipt.read_text()
    else:
        assert "Restoring the previous compatible application release" in result.stderr
        assert not receipt.exists()


@pytest.mark.parametrize("protocol", [[], ["rollback-v2"], ["rollback-v2", "release-contract-v1"]])
def test_legacy_workflow_invocation_is_rejected_before_token_read(protocol: list[str]) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "123", "a" * 40, *protocol],
        input="",
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 1
    assert "rollback-v2 and technical-checks-v1" in result.stderr


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


@pytest.mark.parametrize(
    ("scenario", "error"),
    [
        ("success", ""),
        ("manual", ""),
        ("failed-ci", "successful CI push to main"),
        ("wrong-repository", "successful CI push to main"),
        ("wrong-commit", "successful CI push to main"),
        ("stale-main", "no longer the tip of main"),
        ("missing-job", "missing a passed required job"),
        ("failed-job", "missing a passed required job"),
        ("wrong-job-attempt", "missing a passed required job"),
        ("wrong-deployment", "does not match this invocation"),
        ("generation-change", "Rollback generation changed"),
        ("quiesced-generation-change", ""),
        ("purge-enabled", "audit deletion must be disabled"),
        ("stateful-change", "Production volumes changed"),
        ("schema-change", "Pending database migrations"),
        (
            "runtime-config-fails",
            "runtime configuration differs from the approved production profile",
        ),
        ("backup-fails", ""),
        ("readiness-fails", "connected database"),
        ("asset-mismatch", "served JavaScript differs"),
        ("authorization-fails", "exact-release predeployment authorization failed"),
        ("authorization-mismatch", "mismatched or incomplete predeployment verdict"),
        ("manifest-mismatch", "mismatched or incomplete predeployment verdict"),
        ("validator-missing", "trusted release validator is not installed"),
    ],
)
def test_release_entrypoint_uses_technical_checks(
    tmp_path: Path, scenario: str, error: str
) -> None:
    sha = "a" * 40
    repository = "nirzaf/garrison-investments"
    previous = tmp_path / "releases" / "previous"
    state = tmp_path / "deploy"
    state.mkdir()
    previous.mkdir(parents=True)
    (state / "current").symlink_to(previous)
    (state / "production.env").write_text("LOG_PURGE_ENABLED=false\n")
    (state / "compose.vps.yml").write_text("services: {}\n")
    authorization_dir = state / "authorizations" / sha
    authorization_dir.mkdir(parents=True)
    (authorization_dir / "release_manifest.json").write_text('{"fixture":true}\n')
    (previous / ".env").write_text("LOG_PURGE_ENABLED=false\n")
    (previous / ".images.env").write_text(
        "GARRISON_BACKEND_IMAGE=old-backend\nGARRISON_FRONTEND_IMAGE=old-frontend\n"
    )
    (previous / "SOURCE_COMMIT").write_text("b" * 40)
    (previous / "deploy").mkdir()
    (previous / "deploy/rollback-generation").write_text("1\n")
    (previous / "docker-compose.prod.yml").write_text("old")
    for path in (
        "observability/postgres/init-grafana-db.sh",
        "observability/minio/loki-policy.json",
    ):
        target = previous / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture")

    trusted_dir = tmp_path / "trusted" / "libexec"
    trusted_dir.mkdir(parents=True)
    trusted_validator = trusted_dir / "garrison-release-contract.py"
    if scenario != "validator-missing":
        trusted_validator.write_text(
            """#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import sys

args = sys.argv
state = pathlib.Path(args[args.index('--host-state') + 1])
if '--verify-runtime-config-root' in args:
    with (state.parent / 'events').open('a') as stream:
        stream.write('runtime-config\\n')
    scenario = os.environ.get('scenario')
    if scenario == 'purge-enabled':
        sys.exit('Production audit deletion must be disabled for this release.')
    if scenario == 'runtime-config-fails':
        sys.exit('Candidate runtime configuration differs from the approved host configuration.')
    print('{"status":"runtime_configuration_verified"}')
    raise SystemExit(0)
commit = args[args.index('--commit') + 1]
manifest = state / 'authorizations' / commit / 'release_manifest.json'
manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
with (state.parent / 'events').open('a') as stream:
    stream.write('authorize\\n')
if os.environ.get('scenario') == 'authorization-fails':
    raise SystemExit(3)
if os.environ.get('scenario') == 'authorization-mismatch':
    commit = 'f' * 40
print(json.dumps({
    'phase': 'predeploy',
    'status': 'ready_for_authorized_deployment',
    'accepted_scope_complete': False,
    'ready_for_authorized_deployment': True,
    'source_sha': commit,
    'target_environment': 'production',
    'release_id': 'fixture-release',
    'manifest_sha256': (
        'a' * 64
        if os.environ.get('scenario') == 'manifest-mismatch'
        else manifest_digest
    ),
    'subject_sha256': 'b' * 64,
    'configuration_sha256': 'c' * 64,
    'validator_sha256': 'd' * 64,
    'control_registry_sha256': 'e' * 64,
    'trust_registry_sha256': 'f' * 64,
    'blockers': [],
}))
"""
        )

    ci = {
        "id": 12,
        "path": ".github/workflows/ci.yml",
        "event": "push",
        "status": "completed",
        "conclusion": "failure" if scenario == "failed-ci" else "success",
        "head_branch": "main",
        "head_repository": {
            "full_name": "other/repo" if scenario == "wrong-repository" else repository
        },
        "head_sha": "c" * 40 if scenario == "wrong-commit" else sha,
        "run_attempt": 2,
    }
    deploy_run = {
        "id": 34,
        "run_attempt": 1,
        "status": "in_progress",
        "head_branch": "main",
        "head_repository": {"full_name": repository},
        "path": ".github/workflows/ci.yml"
        if scenario == "wrong-deployment"
        else ".github/workflows/deploy.yml",
        "event": "workflow_dispatch" if scenario == "manual" else "workflow_run",
        # workflow_run's default SHA can differ from the tested SHA.
        "head_sha": sha if scenario == "manual" else "c" * 40,
    }
    names = [
        "Backend lint and types",
        "Frontend lint, types, tests and build",
        "Compose files are valid",
        "Backend tests (1/2)",
        "Backend tests (2/2)",
        "Browser regressions (1/2)",
        "Browser regressions (2/2)",
    ]
    if scenario == "missing-job":
        names.pop()
    jobs = [
        {
            "name": name,
            "run_id": 12,
            "head_sha": sha,
            "status": "completed",
            "run_attempt": 2,
            "conclusion": "success",
        }
        for name in names
    ]
    if scenario == "failed-job":
        jobs[0]["conclusion"] = "failure"
    if scenario == "wrong-job-attempt":
        jobs[0]["run_attempt"] = 1
    for name, payload in {
        "ci": ci,
        "jobs": {"total_count": len(jobs), "jobs": jobs},
        "deploy-run": deploy_run,
        "main": {"object": {"sha": "c" * 40 if scenario == "stale-main" else sha}},
    }.items():
        (tmp_path / name).write_text(json.dumps(payload))

    with tarfile.open(tmp_path / "archive.tgz", "w:gz") as archive:
        for name, payload in {
            "deploy/rollback-generation": "2\n" if "generation-change" in scenario else "1\n",
            "docker-compose.prod.yml": "new",
            "observability/postgres/init-grafana-db.sh": "fixture",
            "observability/minio/loki-policy.json": "fixture",
        }.items():
            body = payload.encode()
            info = tarfile.TarInfo(f"source/{name}")
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))

    # Substitute the privileged host boundary and external commands. Keep the
    # entrypoint's CI, Compose, schema, backup, activation, and receipt logic.
    source = SCRIPT.read_text().replace(
        "base=/opt/garrison-portal", f"base={shlex.quote(str(tmp_path))}"
    )
    source = source.replace(
        "trusted_validator=/usr/local/libexec/garrison-release-contract.py",
        f"trusted_validator={shlex.quote(str(trusted_validator))}",
    )
    start = source.index("# Keep the privileged entrypoint")
    end = source.index('exec 9>"$state/deploy.lock"', start)
    source = source[:start] + "flock() { :; }\n" + source[end:]
    start = source.index("github() {")
    end = source.index("verify_main() {", start)
    source = (
        source[:start]
        + r"""
github() {
  case "$1" in
    actions/runs/12) cat "$base/ci" ;;
    actions/runs/12/attempts/2/jobs*) cat "$base/jobs" ;;
    actions/runs/34/attempts/1) cat "$base/deploy-run" ;;
    git/ref/heads/main) cat "$base/main" ;;
    tarball/*) echo download >> "$base/events"; cat "$base/archive.tgz" ;;
    *) return 43 ;;
  esac
}
docker() {
  case "$1 $2" in
    'ps --filter') [[ "$scenario" == quiesced-generation-change ]] || echo nginx ;;
    'image inspect') printf 'sha256:%s\n' "$asset_digest" ;;
    'exec garrison-portal-postgres-1') echo fixture-head ;;
    'exec garrison-portal-nginx-1') : ;;
    'inspect --format') printf 'sha256:%s\n' "$asset_digest" ;;
    'run --rm')
      if [[ "$*" == *alembic* ]]; then
        if [[ "$scenario" == schema-change && "$*" != *old-backend* ]]; then
          echo candidate-head
        else
          echo fixture-head
        fi
      elif [[ "$*" == *'/site'* ]]; then
        echo "publish ${7}" >> "$base/events"
      else
        printf '%s /assets/index-test.js %s %s\n' "$asset_digest" "$asset_digest" "$asset_digest"
      fi ;;
    'compose --project-name')
      local location=$5
      shift 13
      case "$1" in
        config)
          python3 - "$scenario" "$location" <<'PYTHON'
import json, sys
from pathlib import Path
scenario, location = sys.argv[1:]
candidate = Path(location).name != "previous"
stateful = ("postgres", "redis", "minio", "grafana_db_init", "loki_minio_init")
services = dict.fromkeys(stateful, {})
services.update({name: {"environment": {
    "LOG_PURGE_ENABLED": "true" if scenario == "purge-enabled" and candidate else "false"
}} for name in ("backend", "celery_worker", "celery_beat")})
print(json.dumps({"volumes": {"other": {}} if candidate and scenario == "stateful-change" else {},
                  "networks": {}, "services": services}))
PYTHON
          ;;
        build|pull) : ;;
        run)
          [[ "$*" == *'--target all --skip-retention' ]] || return 43
          echo backup >> "$base/events"
          [[ "$scenario" != backup-fails ]] ;;
        up) echo "activate ${location##*/}" >> "$base/events" ;;
        ps) echo fixture-container ;;
        *) return 43 ;;
      esac ;;
    *) return 43 ;;
  esac
}
curl() {
  local url="${*: -1}"
  if [[ "$url" == */health/readiness ]]; then
    if [[ "$scenario" == readiness-fails ]]; then
      echo '{"status":"not_ready","database":"disconnected"}'
    else
      echo '{"status":"ready","database":"connected"}'
    fi
  elif [[ "$scenario" == asset-mismatch && "$url" == */assets/index-test.js ]]; then
    printf 'wrong asset'
  else
    printf 'fixture asset'
  fi
}
"""
        + source[end:]
    )
    # GNU mv's -T flag is unavailable on macOS. Preserve the atomic rename
    # semantics for the fixture without touching the production invocation.
    source = source.replace("export PATH=/usr/sbin:/usr/bin:/sbin:/bin", "", 1)
    source = source.replace(
        'mv -Tf "$state/.current-next" "$state/current"',
        'python3 -c "import os, sys; os.replace(*sys.argv[1:])" '
        '"$state/.current-next" "$state/current"',
    )
    script = tmp_path / "entrypoint.sh"
    script.write_text(source)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f"scenario={shlex.quote(scenario)} asset_digest={sha256(b'fixture asset').hexdigest()} "
            f"bash {shlex.quote(str(script))} 12 {sha} rollback-v2 technical-checks-v1",
        ],
        input="fixture-token\n34\n1\n",
        capture_output=True,
        check=False,
        text=True,
    )
    current = (state / "current").resolve()
    events_path = tmp_path / "events"
    events = events_path.read_text().splitlines() if events_path.exists() else []
    if scenario in {"success", "manual", "quiesced-generation-change"}:
        assert result.returncode == 0, result.stderr
        assert current != previous
        receipt = deployment_receipt_fields((current / "DEPLOYED").read_bytes())
        asset_digest = sha256(b"fixture asset").hexdigest()
        image = f"sha256:{asset_digest}"
        verify_host_deployment_receipt(
            receipt,
            {"ci_run_id": 12, "ci_run_attempt": 2, "run_id": 34, "run_attempt": 1},
            sha,
            {
                "frontend_sha256": asset_digest,
                "service_worker_sha256": asset_digest,
                "image_digests": {"backend": image, "frontend": image},
                "schema_heads": ["fixture-head"],
            },
            utc(receipt["UTC"], "fixture activation"),
            sha256((current / "PREDEPLOY.json").read_bytes()).hexdigest(),
            sha256((current / "PREDEPLOY_MANIFEST.json").read_bytes()).hexdigest(),
        )
        assert events[:4] == ["authorize", "download", "runtime-config", "backup"]
        assert events[4].startswith("activate ")
        assert events[5].startswith("publish ")
        assert (current / "PREDEPLOY.json").is_file()
        assert (current / "PREDEPLOY_MANIFEST.json").is_file()
        assert sha256((current / "PREDEPLOY_MANIFEST.json").read_bytes()).hexdigest() == (
            sha256((authorization_dir / "release_manifest.json").read_bytes()).hexdigest()
        )
        predeploy_digest = sha256((current / "PREDEPLOY.json").read_bytes()).hexdigest()
        assert f"Predeploy verdict SHA-256: {predeploy_digest}" in (
            current / "DEPLOYED"
        ).read_text()
        assert "Predeploy manifest SHA-256" in (current / "DEPLOYED").read_text()
    else:
        assert result.returncode != 0, result.stdout
        assert error in result.stderr
        assert current == previous
        assert not list((tmp_path / "releases").glob("*/DEPLOYED"))
        if scenario in {"authorization-fails", "authorization-mismatch", "manifest-mismatch"}:
            assert events == ["authorize"]
        elif scenario == "validator-missing":
            assert not events
        elif scenario in {"readiness-fails", "asset-mismatch"}:
            assert "activate previous" in events
            assert events[-1] == "publish old-frontend"
        elif scenario == "backup-fails":
            assert events == ["authorize", "download", "runtime-config", "backup"]
        elif scenario in {"purge-enabled", "runtime-config-fails"}:
            assert events == ["authorize", "download", "runtime-config"]
        elif scenario == "generation-change":
            assert events == ["authorize", "download"]
        elif scenario in {"stateful-change", "schema-change"}:
            assert events == ["authorize", "download", "runtime-config"]
        else:
            assert not events


def test_host_release_requires_trusted_predeployment_verdict() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    deploy_source = (repo_root / ".github" / "workflows" / "deploy.yml").read_text()
    release_source = SCRIPT.read_text()
    assert "/usr/local/libexec/garrison-release-contract.py" not in deploy_source
    assert "trusted_validator=/usr/local/libexec/garrison-release-contract.py" in release_source
    assert "--host-state \"$state\" --commit \"$sha\"" in release_source
    assert "PREDEPLOY.json" in release_source
    assert "PREDEPLOY_MANIFEST.json" in release_source
    assert "--verify-runtime-config-root \"$candidate\"" in release_source
    assert "Predeploy verdict SHA-256" in release_source
    assert "Predeploy manifest SHA-256" in release_source


def test_production_workflow_requires_verified_host_gate_readiness() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    deploy_source = (repo_root / ".github" / "workflows" / "deploy.yml").read_text()
    assert "vars.GARRISON_PREDEPLOY_GATE_READY == 'true'" in deploy_source
    assert "runs-on: [self-hosted, linux, x64, garrison-production]" in deploy_source


def test_audit_purge_defaults_disabled_and_env_example_documents_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("LOG_PURGE_ENABLED", raising=False)
    assert Settings.model_fields["log_purge_enabled"].default is False
    assert Settings().log_purge_enabled is False
    assert "LOG_PURGE_ENABLED=false" in (repo_root / ".env.example").read_text().splitlines()
