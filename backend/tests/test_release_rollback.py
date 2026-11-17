import io
import json
import runpy
import shlex
import subprocess
import tarfile
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from scripts.release_contract import deployment_receipt_fields, utc, verify_host_deployment_receipt

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "hostinger-release.sh"


def _support_tls_fixture(certificate: Path, key: Path, fault: str | None) -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    label = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "superadmin.garrisons.lk")])
    now = datetime.now(UTC)
    start = now + timedelta(days=1) if fault == "future-cert" else now - timedelta(days=2)
    end = now - timedelta(days=1) if fault == "expired-cert" else now + timedelta(days=2)
    builder = (
        x509.CertificateBuilder()
        .subject_name(label)
        .issuer_name(label)
        .public_key(private.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(start)
        .not_valid_after(end)
    )
    if fault != "cn-only-cert":
        names = {
            "wrong-cert-host": "portal.garrisons.lk",
            "wildcard-cert": "*.garrisons.lk",
        }
        address = names.get(fault or "", "superadmin.garrisons.lk")
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(address)]), False)
    built = builder.sign(private, hashes.SHA256())
    certificate.write_bytes(
        b"not a certificate"
        if fault == "bad-pem" else built.public_bytes(serialization.Encoding.PEM)
    )
    if fault == "mismatched-cert-key":
        private = ec.generate_private_key(ec.SECP256R1())
    encoding = (
        serialization.BestAvailableEncryption(b"synthetic-passphrase")
        if fault == "encrypted-key" else serialization.NoEncryption()
    )
    key.write_bytes(private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, encoding,
    ))
    key.chmod(0o644 if fault == "key-mode" else 0o600)


@pytest.mark.parametrize(
    ("fault", "expected_error"),
    [
        (None, None),
        ("no-host", "enabled together"),
        ("flag-off", "enabled together"),
        ("other-host-file", "tested candidate"),
        ("writable-mount", "mounted read-only"),
        ("forwarded-peer", "must use the socket peer"),
        ("contradictory-peer", "must use the socket peer"),
        ("wrong-peer", "private backend peer"),
        ("missing-tls", "TLS pair"),
        ("key-mode", "TLS key must be private"),
        ("wrong-cert-host", "DNS SAN for superadmin.garrisons.lk"),
        ("cn-only-cert", "DNS SAN for superadmin.garrisons.lk"),
        ("wildcard-cert", None),
        ("expired-cert", "outside its validity period"),
        ("future-cert", "outside its validity period"),
        ("mismatched-cert-key", "private key do not load together"),
        ("encrypted-key", "private key do not load together"),
        ("bad-pem", "private key do not load together"),
        ("empty-allowlist", "no approved"),
        ("wide-allowlist", "bounded, explicit IP networks"),
        ("combined-ipv4", "collectively allow every address"),
        ("combined-ipv6", "collectively allow every address"),
        ("other-directive", "bounded, explicit IP networks"),
        ("otp-key-absent", "independent email OTP key"),
        ("otp-key-reused", "independent email OTP key"),
        ("otp-missing-second", "distinct OTP mailbox bindings"),
        ("otp-duplicate-mailbox", "distinct OTP mailbox bindings"),
        ("otp-duplicate-operator", "distinct OTP mailbox bindings"),
        ("otp-duplicate-json-key", "distinct OTP mailbox bindings"),
        ("otp-bad-reference", "distinct OTP mailbox bindings"),
        ("otp-bad-mailbox", "distinct OTP mailbox bindings"),
    ],
)
def test_production_support_ingress_configuration(
    tmp_path: Path, fault: str | None, expected_error: str | None
) -> None:
    validate = runpy.run_path(str(SCRIPT.parent / "release_config_contract.py"))[
        "validate_support_ingress"
    ]
    host = "/etc/nginx/conf.d/support.conf"
    tls = "/etc/nginx/ssl/"
    nginx = {
        "networks": {"backend_proxy": {"ipv4_address": "192.0.2.10"}},
        "volumes": [{"target": host, "read_only": fault != "writable-mount"}],
    }
    env = {
        "SUPPORT_PORTAL_ENABLED": "false" if fault == "flag-off" else "true",
        "SUPPORT_INGRESS_PEER": "192.0.2.11" if fault == "wrong-peer" else "192.0.2.10",
        "SUPPORT_EMAIL_OTP_KEY": "test-only-otp-key-not-runtime-config",
    }
    first = "a4f0517e-d4e4-4a91-83c8-77d9c5d0478f"
    second = "ccbad879-60fc-4ac1-b82c-27ff391fe6a1"
    addresses = {
        first: "synthetic-first@example.com",
        second: "synthetic-second@example.com",
    }
    if fault == "otp-key-absent":
        env.pop("SUPPORT_EMAIL_OTP_KEY")
    if fault == "otp-key-reused":
        env["SUPPORT_RECOVERY_KEY"] = env["SUPPORT_EMAIL_OTP_KEY"]
    if fault == "otp-missing-second":
        del addresses[second]
    if fault == "otp-duplicate-mailbox":
        addresses[second] = addresses[first].upper()
    if fault == "otp-duplicate-operator":
        addresses[first.upper()] = addresses.pop(second)
    if fault == "otp-bad-reference":
        addresses["bad-reference"] = addresses.pop(second)
    if fault == "otp-bad-mailbox":
        addresses[second] = "synthetic-secret-marker"
    env["SUPPORT_EMAIL_OTP_RECIPIENTS"] = json.dumps(addresses)
    if fault == "otp-duplicate-json-key":
        env["SUPPORT_EMAIL_OTP_RECIPIENTS"] = (
            f'{{"{first}":"synthetic-first@example.com",'
            f'"{first}":"synthetic-other@example.com","{second}":"synthetic-second@example.com"}}'
        )
    tls_key = tmp_path / "key.pem"
    certificate = tmp_path / "cert.pem"
    _support_tls_fixture(certificate, tls_key, fault)
    allowlist = tmp_path / "support-allowlist.conf"
    allowlist.write_text({
        "empty-allowlist": "# No active networks\n",
        "wide-allowlist": "allow 0.0.0.0/0;\n",
        "combined-ipv4": "allow 0.0.0.0/1;\nallow 128.0.0.0/1;\n",
        "combined-ipv6": "allow ::/1;\nallow 8000::/1;\n",
        "other-directive": "allow 192.0.2.20;\nsatisfy any;\n",
    }.get(fault or "", "allow 192.0.2.20; # fixture\nallow 2001:db8::/64;\n"))
    vhost = "other.conf" if fault == "other-host-file" else "nginx/support.prod.conf"
    files = {
        host: tmp_path / vhost,
        tls + "support-fullchain.pem": certificate,
        tls + "support-privkey.pem": tls_key,
        tls + "support-allowlist.conf": allowlist,
    }
    if fault == "no-host":
        files.pop(host)
    if fault == "missing-tls":
        files.pop(tls + "support-fullchain.pem")
    command = ["uvicorn", "app.main:app"]
    if fault != "forwarded-peer":
        command.append("--no-proxy-headers")
    if fault == "contradictory-peer":
        command.append("--proxy-headers")
    backend = {"command": command}
    validate(tmp_path, {}, {}, {}, {})
    if expected_error:
        with pytest.raises(ValueError, match=expected_error) as rejected:
            validate(tmp_path, nginx, backend, env, files)
        assert "synthetic-secret-marker" not in str(rejected.value)
        assert "test-only-otp-key" not in str(rejected.value)
    else:
        validate(tmp_path, nginx, backend, env, files)


@pytest.mark.parametrize("job_attempt", [2, 3])
def test_deployment_receipt_records_only_the_ci_attempt_that_passed(
    tmp_path: Path, job_attempt: int
) -> None:
    source = SCRIPT.read_text()
    start = source.index("\nverify_ci() {\n")
    end = source.index("\nverify_deploy_run() {", start)
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
        receipt_text = receipt.read_text()
        assert receipt_text.splitlines()[1:6] == [
            f"Commit: {sha}",
            "CI run: 123",
            "CI attempt: 2",
            "Deploy run: 456",
            "Deploy attempt: 1",
        ]
        assert "Predeploy verdict SHA-256" not in receipt_text
        assert "Predeploy manifest SHA-256" not in receipt_text
    else:
        assert result.returncode != 0
        assert not receipt.exists()
        assert "missing a passed required job" in result.stderr


@pytest.mark.parametrize(
    ("run_status", "accepted"),
    [("queued", True), ("in_progress", True), ("completed", False), ("waiting", False)],
)
def test_active_deployment_run_status_allows_api_propagation_delay(
    run_status: str, accepted: bool
) -> None:
    source = SCRIPT.read_text()
    start = source.index("\nverify_deploy_run() {\n")
    end = source.index("\nverify_deploy_run\n", start)
    sha = "a" * 40
    repository = "nirzaf/garrison-investments"
    run = json.dumps({
        "id": 456,
        "run_attempt": 1,
        "path": ".github/workflows/deploy.yml",
        "status": run_status,
        "head_branch": "main",
        "head_repository": {"full_name": repository},
        "event": "workflow_run",
        "head_sha": sha,
    })
    result = subprocess.run(
        ["bash", "-c", f"""
set -euo pipefail
deploy_run_id=456
deploy_attempt=1
repository={repository}
sha={sha}
github() {{
  case "$1" in
    actions/runs/456/attempts/1) printf '%s\\n' {shlex.quote(run)} ;;
    *) return 2 ;;
  esac
}}
{source[start:end]}
verify_deploy_run
"""],
        capture_output=True,
        check=False,
        text=True,
    )
    if accepted:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "does not match this invocation" in result.stderr


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
        ("purge-enabled", "mismatched keys: LOG_PURGE_ENABLED"),
        ("stateful-change", "Production volumes changed"),
        ("schema-change", "Pending database migrations"),
        (
            "missing-config",
            "technical configuration, secret/TLS/key, or log-retention safety validation",
        ),
        (
            "missing-tls-or-key",
            "technical configuration, secret/TLS/key, or log-retention safety validation",
        ),
        (
            "unsafe-bind-mount",
            "technical configuration, secret/TLS/key, or log-retention safety validation",
        ),
        ("backup-fails", ""),
        ("readiness-fails", "connected database"),
        ("asset-mismatch", "served JavaScript differs"),
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
    (state / "production.env").write_text(
        "LOG_PURGE_ENABLED=false\n"
        "JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private_key\n"
        "JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public_key\n"
    )
    (state / "production.env").chmod(0o600)
    (state / "compose.vps.yml").write_text("services: {}\n")
    (state / "compose.vps.yml").chmod(0o644)

    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(mode=0o755)
    jwt_priv = secrets_dir / "jwt_private_key"
    jwt_pub = secrets_dir / "jwt_public_key"
    if scenario != "missing-tls-or-key":
        jwt_priv.write_text("private-key-fixture\n")
        jwt_priv.chmod(0o664 if scenario == "unsafe-bind-mount" else 0o600)
    jwt_pub.write_text("public-key-fixture\n")
    jwt_pub.chmod(0o644)

    ssl_dir = tmp_path / "deploy" / "ssl"
    ssl_dir.mkdir(mode=0o755)
    for cert_name in ("fullchain.pem", "privkey.pem"):
        cert_file = ssl_dir / cert_name
        cert_file.write_text(f"{cert_name}-fixture\n")
        cert_file.chmod(0o644)

    (previous / ".env").write_bytes((state / "production.env").read_bytes())
    (previous / ".env").chmod(0o600)
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
        target.chmod(0o644)

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

    archive_files = {
        "deploy/rollback-generation": "2\n" if "generation-change" in scenario else "1\n",
        "deploy/release_config_contract.py": (
            SCRIPT.parent / "release_config_contract.py"
        ).read_text(),
        "docker-compose.prod.yml": "new",
        "observability/postgres/init-grafana-db.sh": "fixture",
        "observability/minio/loki-policy.json": "fixture",
    }
    if scenario == "missing-config":
        del archive_files["observability/minio/loki-policy.json"]

    with tarfile.open(tmp_path / "archive.tgz", "w:gz") as archive:
        for name, payload in archive_files.items():
            body = payload.encode()
            info = tarfile.TarInfo(f"source/{name}")
            info.size = len(body)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(body))

    # Substitute the privileged host boundary and external commands. Keep the
    # entrypoint's CI, Compose, schema, backup, activation, and receipt logic.
    source = SCRIPT.read_text().replace(
        "base=/opt/garrison-portal", f"base={shlex.quote(str(tmp_path))}"
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
          python3 - "$scenario" "$location" "$base" <<'PYTHON'
import json, sys
from pathlib import Path
scenario, location, base = sys.argv[1:]
candidate = Path(location).name != "previous"
if candidate and not (Path(base) / ".config_checked").exists():
    (Path(base) / ".config_checked").write_text("1")
    with (Path(base) / "events").open("a") as stream:
        stream.write("runtime-config\n")
stateful = ("postgres", "redis", "minio", "grafana_db_init", "loki_minio_init")
services = dict.fromkeys(stateful, {})
backend_volumes = [
    {
        "type": "bind",
        "source": f"{base}/secrets/jwt_public_key",
        "target": "/run/secrets/jwt_public_key",
    },
]
if scenario != "missing-tls-or-key":
    backend_volumes.insert(
        0,
        {
            "type": "bind",
            "source": f"{base}/secrets/jwt_private_key",
            "target": "/run/secrets/jwt_private_key",
        },
    )
for name in ("backend", "celery_worker", "celery_beat"):
    environment = {
        "LOG_PURGE_ENABLED": "true" if scenario == "purge-enabled" and candidate else "false",
        "JWT_PRIVATE_KEY_PATH": "/run/secrets/jwt_private_key",
        "JWT_PUBLIC_KEY_PATH": "/run/secrets/jwt_public_key",
    }
    services[name] = {
        # Compose config --format json flattens env_file values into the
        # effective environment instead of retaining their source paths.
        "env_file": [],
        "environment": environment,
        "volumes": backend_volumes if name == "backend" else [],
    }
services["nginx"] = {
    "volumes": [
        {"type": "bind", "source": f"{base}/deploy/ssl", "target": "/etc/nginx/ssl"},
    ]
}
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
        assert not (current / "PREDEPLOY.json").exists()
        assert not (current / "PREDEPLOY_MANIFEST.json").exists()
        deployed_text = (current / "DEPLOYED").read_text()
        assert "Predeploy" not in deployed_text
        receipt = deployment_receipt_fields(deployed_text.encode())
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
        )
        assert events[:3] == ["download", "runtime-config", "backup"]
        assert events[3].startswith("activate ")
        assert events[4].startswith("publish ")
    else:
        assert result.returncode != 0, result.stdout
        assert error in result.stderr
        assert current == previous
        assert not list((tmp_path / "releases").glob("*/DEPLOYED"))
        if scenario in {"readiness-fails", "asset-mismatch"}:
            assert "activate previous" in events
            assert events[-1] == "publish old-frontend"
        elif scenario == "backup-fails":
            assert events == ["download", "runtime-config", "backup"]
        elif scenario in {
            "purge-enabled",
            "missing-config",
            "missing-tls-or-key",
            "unsafe-bind-mount",
            "stateful-change",
            "schema-change",
        }:
            assert events == ["download", "runtime-config"]
        elif scenario == "generation-change":
            assert events == ["download"]
        else:
            assert not events


def test_host_release_does_not_depend_on_formal_approval_validator() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    deploy_source = (repo_root / ".github" / "workflows" / "deploy.yml").read_text()
    release_source = SCRIPT.read_text()
    for forbidden in (
        "garrison-release-contract.py",
        "PREDEPLOY.json",
        "PREDEPLOY_MANIFEST.json",
        "Predeploy verdict SHA-256",
        "Predeploy manifest SHA-256",
        "authorized-configuration.json",
        "approval-trust.json",
    ):
        assert forbidden not in release_source
        assert forbidden not in deploy_source
    assert "LOG_PURGE_ENABLED" in release_source
    assert "Deployed — Formal Acceptance Pending" in release_source
    assert "/etc/nginx/ssl" in release_source
    assert "/run/secrets/jwt_private_key" in release_source


def test_production_workflow_triggers_without_predeploy_gate_variable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    deploy_source = (repo_root / ".github" / "workflows" / "deploy.yml").read_text()
    assert "GARRISON_PREDEPLOY_GATE_READY" not in deploy_source
    assert "workflow_run:" in deploy_source
    assert "workflow_dispatch:" in deploy_source
    assert "ci_run_id:" in deploy_source
    assert "github.ref == 'refs/heads/main'" in deploy_source
    assert "github.event.workflow_run.conclusion == 'success'" in deploy_source
    assert "github.event.workflow_run.head_branch == 'main'" in deploy_source
    assert (
        "github.event.workflow_run.head_repository.full_name == github.repository"
        in deploy_source
    )
    assert "group: garrison-portal-production" in deploy_source
    assert "runs-on: [self-hosted, linux, x64, garrison-production]" in deploy_source
    assert "sudo -n /usr/local/sbin/garrison-deploy" in deploy_source


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        ("valid", ""),
        ("world-readable-env", "Production secrets must be readable only by root."),
        (
            "group-writable-compose",
            "Production configuration must be protected from runner writes.",
        ),
        (
            "group-writable-state-dir",
            "Production deployment directories must be protected from runner writes.",
        ),
        (
            "symlink-state-dir",
            "Production deployment directories must be root-owned and free of symlinks.",
        ),
    ],
)
def test_host_configuration_permissions_are_enforced_before_lock(
    tmp_path: Path, mutation: str, expected_error: str
) -> None:
    opt_dir = tmp_path / "opt"
    base = opt_dir / "garrison-portal"
    state = base / "deploy"
    releases = base / "releases"
    for d in (opt_dir, base, state, releases):
        d.mkdir(parents=True, mode=0o755)
        d.chmod(0o755)
    prod_env = state / "production.env"
    compose_vps = state / "compose.vps.yml"
    prod_env.write_text("LOG_PURGE_ENABLED=false\n")
    prod_env.chmod(0o600)
    compose_vps.write_text("services: {}\n")
    compose_vps.chmod(0o644)

    if mutation == "world-readable-env":
        prod_env.chmod(0o644)
    elif mutation == "group-writable-compose":
        compose_vps.chmod(0o664)
    elif mutation == "group-writable-state-dir":
        state.chmod(0o775)
    elif mutation == "symlink-state-dir":
        real_state = tmp_path / "real-deploy"
        state.rename(real_state)
        state.symlink_to(real_state)

    source = SCRIPT.read_text()
    start = source.index('for directory in /opt "$base" "$state" "$base/releases"; do')
    end = source.index('exec 9>"$state/deploy.lock"', start)
    snippet = source[start:end].replace(
        "for directory in /opt ", f"for directory in {shlex.quote(str(opt_dir))} "
    )

    result = subprocess.run(
        [
            "bash",
            "-c",
            f"""
set -euo pipefail
base={shlex.quote(str(base))}
state={shlex.quote(str(state))}
die() {{ printf '%s\\n' "$*" >&2; exit 1; }}
stat() {{
  if [[ "$1" == "-c" && "$2" == "%a" ]]; then
    python3 -c \\
      'import os, stat, sys; print(oct(stat.S_IMODE(os.lstat(sys.argv[1]).st_mode))[2:])' "$3"
  else
    command stat "$@"
  fi
}}
{snippet}
""",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if mutation == "valid":
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert expected_error in result.stderr


def test_audit_purge_defaults_disabled_and_env_example_documents_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import Settings

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("LOG_PURGE_ENABLED", raising=False)
    assert Settings.model_fields["log_purge_enabled"].default is False
    assert Settings().log_purge_enabled is False
    assert "LOG_PURGE_ENABLED=false" in (repo_root / ".env.example").read_text().splitlines()
