"""Opt-in disposable actual API/Postgres/TLS ingress test, not host enrollment."""

import importlib.util
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("guard", ROOT / "deploy/maintenance_ingress.py")
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.skipif(os.getenv("RUN_FORWARD097_STACK") != "1", reason="Disposable Docker opt-in")
@pytest.mark.parametrize(
    "use_dispatch",
    [False, "success", "migration_failure", "activation_failure", "reopen_kill"],
    ids=["controls", "dispatch", "migration_failure", "activation_failure", "reopen_kill"],
)
def test_actual_api_tls_drain_and_controlled_reopen(tmp_path, use_dispatch):
    prefix = "garrison-f097-" + uuid.uuid4().hex[:10]
    network = prefix + "-private"
    names = []
    image = "garrison-forward097-synthetic:local"

    def docker(*args):
        return subprocess.run(["docker", *args], text=True, capture_output=True, check=True).stdout

    def run(suffix, runtime, *args, options=()):
        name = prefix + "-" + suffix
        names.append(name)
        service = {
            "ingress": "nginx",
            "backend": "backend",
            "worker": "celery_worker",
            "beat": "celery_beat",
        }.get(suffix)
        if service:
            options = (
                *options,
                "--label",
                f"com.docker.compose.project={prefix}",
                "--label",
                f"com.docker.compose.service={service}",
            )
        docker(
            "run",
            "-d",
            "--name",
            name,
            "--network",
            network,
            "--network-alias",
            suffix,
            *options,
            runtime,
            *args,
        )
        return name

    def sql(query):
        return docker("exec", db, "psql", "-U", "fixture", "-d", "fixture", "-Atc", query).strip()

    def wait_ready(name):
        for _ in range(60):
            result = subprocess.run(
                ["docker", "exec", name, "curl", "-fsS", "http://127.0.0.1:8000/health/readiness"],
                capture_output=True,
            )
            if result.returncode == 0:
                return
            time.sleep(0.5)
        result = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        pytest.fail("Synthetic API startup failed: " + (result.stdout + result.stderr)[-3000:])

    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-keyout",
            str(tmp_path / "key.pem"),
            "-out",
            str(tmp_path / "cert.pem"),
            "-subj",
            "/CN=synthetic.invalid",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-in",
            str(tmp_path / "key.pem"),
            "-pubout",
            "-out",
            str(tmp_path / "public.pem"),
        ],
        check=True,
        capture_output=True,
    )
    base = """events {}\nhttp {\nserver {\nlisten 8443 ssl;
ssl_certificate /fixture/cert.pem; ssl_certificate_key /fixture/key.pem;
location /health/readiness { proxy_pass http://backend:8000; }
location /api/ { proxy_pass http://backend:8000; }
location / { return 200 'synthetic static'; }
}\n}\n"""
    config = tmp_path / "nginx.conf"
    config.write_text(guard.guarded_config(base))
    docker("network", "create", "--internal", network)
    try:
        db = run(
            "db",
            "postgres:18.6-alpine",
            options=(
                "-e",
                "POSTGRES_USER=fixture",
                "-e",
                "POSTGRES_PASSWORD=synthetic-only",
                "-e",
                "POSTGRES_DB=fixture",
            ),
        )
        run("redis", "redis:7-alpine")
        for _ in range(60):
            if (
                subprocess.run(
                    ["docker", "exec", db, "pg_isready", "-U", "fixture"], capture_output=True
                ).returncode
                == 0
            ):
                break
            time.sleep(0.5)
        opts = (
            "-v",
            f"{ROOT / 'backend'}:/app:ro",
            "-v",
            f"{tmp_path}:/fixture:ro",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "APP_ENV=production",
            "-e",
            "DATABASE_URL=postgresql+asyncpg://fixture:synthetic-only@db:5432/fixture",
            "-e",
            "REDIS_URL=redis://redis:6379/0",
            "-e",
            "EXCEPTION_EMAIL_ENABLED=false",
            "-e",
            "JWT_PRIVATE_KEY_PATH=/fixture/key.pem",
            "-e",
            "JWT_PUBLIC_KEY_PATH=/fixture/public.pem",
        )
        docker(
            "run", "--rm", "--network", network, *opts, image, "alembic", "upgrade", "202605310093"
        )
        assert sql("select version_num from alembic_version") == "202605310093"
        assert (
            sql(
                "select count(*) from pg_stat_activity "
                "where datname='fixture' and pid<>pg_backend_pid()"
            )
            == "0"
        )
        guard.verify_drained({"postgres", "redis"}, 0)
        if not use_dispatch or use_dispatch == "reopen_kill":
            docker(
                "run",
                "--rm",
                "--network",
                network,
                *opts,
                image,
                "alembic",
                "upgrade",
                "202605310097",
            )
            assert sql("select version_num from alembic_version") == "202605310097"
        backend = run(
            "backend",
            image,
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            "8000",
            options=opts,
        )
        wait_ready(backend)
        assert int(sql("select count(*) from activity_log where action='system.startup'")) == 1
        nginx = run(
            "ingress",
            "nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3",
            options=("-v", f"{tmp_path}:/fixture:ro", "-v", f"{config}:/etc/nginx/nginx.conf:ro"),
        )
        docker("exec", nginx, "nginx", "-t")

        def request(path, method="GET"):
            return docker(
                "exec",
                backend,
                "curl",
                "-ksS",
                "-o",
                "/dev/null",
                "-w",
                "%{http_code}",
                "-X",
                method,
                "https://ingress:8443" + path,
            )

        before = sql("select count(*) from activity_log")
        assert request("/health/readiness") == "200"
        for path in (
            "/api/v1/projects",
            "/api/v1/auth/login",
            "/api/v1/support",
            "/portal-files/a",
        ):
            assert request(path) == "503"
        assert request("/health/readiness", "POST") == "503"
        assert sql("select count(*) from activity_log") == before
        for name in (backend, nginx, db):
            ports = json.loads(docker("inspect", name))[0]["HostConfig"]["PortBindings"]
            assert not ports  # no host-published direct backend or DB in disposable fixture
        # Real worker is reopened only after smoke; beat stays absent in this bounded fixture.
        worker = run(
            "worker",
            image,
            "celery",
            "-A",
            "app.tasks.celery_app.celery_app",
            "worker",
            "-Q",
            "synthetic-empty",
            "--pool=solo",
            "--loglevel=WARNING",
            options=opts,
        )
        for _ in range(30):
            ping = subprocess.run(
                [
                    "docker",
                    "exec",
                    worker,
                    "celery",
                    "-A",
                    "app.tasks.celery_app.celery_app",
                    "inspect",
                    "ping",
                    "--timeout=1",
                ],
                capture_output=True,
                text=True,
            )
            if ping.returncode == 0 and "pong" in ping.stdout:
                break
            time.sleep(0.2)
        assert ping.returncode == 0 and "pong" in ping.stdout
        assert request("/api/v1/projects") == "503"
        adapter_spec = importlib.util.spec_from_file_location(
            "concrete_adapter", ROOT / "deploy/compose_maintenance.py"
        )
        assert adapter_spec and adapter_spec.loader
        adapter_module = importlib.util.module_from_spec(adapter_spec)
        adapter_spec.loader.exec_module(adapter_module)
        beat = run(
            "beat",
            image,
            "celery",
            "-A",
            "app.tasks.celery_app.celery_app",
            "beat",
            "--schedule=/tmp/synthetic-celerybeat",
            "--loglevel=INFO",
            options=opts,
        )
        time.sleep(2)
        assert json.loads(docker("inspect", beat))[0]["State"]["Running"]
        adapter = adapter_module.ComposeMaintenance(
            prefix,
            {"nginx": nginx, "backend": backend, "celery_worker": worker, "celery_beat": beat},
        )
        # A real unexpected producer under the same Compose project must stop dispatch.
        unknown = run(
            "unknown-producer",
            "redis:7-alpine",
            options=(
                "--label",
                f"com.docker.compose.project={prefix}",
                "--label",
                "com.docker.compose.service=unreviewed_producer",
            ),
        )
        with pytest.raises(ValueError, match="Unknown project container"):
            adapter.drain_fixture()
        assert adapter.snapshot("backend")["State"]["Running"]
        assert adapter.snapshot("nginx")["State"]["Running"]
        docker("rm", "-f", "-v", unknown)  # only this disposable synthetic producer
        names.remove(unknown)
        if use_dispatch == "reopen_kill":
            import signal

            state = tmp_path / "commit-state"
            candidate = state / "candidate"
            candidate.mkdir(parents=True)
            (candidate / "FORWARD_VERIFIED").write_text("synthetic guarded verification")
            (state / "current").symlink_to(candidate)
            (state / "forward097.attempt").write_text("synthetic in progress\n")
            unguarded = tmp_path / "unguarded.conf"
            unguarded.write_text(base)
            image_id = json.loads(docker("inspect", backend))[0]["Image"]
            env = dict(
                os.environ,
                STATE=str(state),
                CANDIDATE=str(candidate),
                PROJECT=prefix,
                BACKEND=backend,
                WORKER=worker,
                BEAT=beat,
                INGRESS=nginx,
                CONFIG=str(config),
                UNGUARDED=str(unguarded),
                IMAGE=image_id,
            )
            script = r"""set -euo pipefail
source "$1"
state=$STATE; candidate=$CANDIDATE; project=$PROJECT; backend_id=$IMAGE
sha=d8e147c1b65c0dfda1071edcc7f05efd4f1181e0
run_id=1; ci_attempt=1; deploy_run_id=1; deploy_attempt=1
portal=https://ingress:8443; asset=/assets/fixture.js
expected=$(printf 'synthetic static' | shasum -a 256 | cut -d' ' -f1)
expected_asset=$expected; expected_worker=$expected
hash() { shasum -a 256 | cut -d' ' -f1; }
check_readiness() { python3 -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"]=="ready" and r["database"]=="connected"
'; }
curl() { command docker exec "$BACKEND" curl -k "$@"; }
compose() {
 shift
 if [[ "$*" == 'ps -q celery_worker' ]]; then echo "$WORKER"
 elif [[ "$*" == 'ps -q celery_beat' ]]; then echo "$BEAT"
 elif [[ "$*" == *'celery_worker celery_beat' ]]; then
  command docker start "$WORKER" "$BEAT" >/dev/null
 elif [[ "$*" == *'150 nginx' ]]; then
  cp "$UNGUARDED" "$CONFIG"
  command docker restart "$INGRESS" >/dev/null
  touch "$state/nginx-transition-returned"
  while true; do sleep 1; done
 else return 70; fi
}
forward_reopen
"""
            # Supervisor injects SIGKILL after real TLS ingress switches, not host code.
            proc = subprocess.Popen(
                ["bash", "-c", script, "fixture", str(ROOT / "deploy/forward097-runtime.sh")],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                for _ in range(120):
                    if (state / "nginx-transition-returned").exists():
                        break
                    if proc.poll() is not None:
                        pytest.fail("Exact reopening shell failed: " + proc.communicate()[1])
                    time.sleep(0.5)
                assert (state / "nginx-transition-returned").exists()
                assert request("/api/v1/projects") in ("401", "403", "307")
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
                commit = json.loads((state / "forward097.reopen-commit").read_text())
                assert commit["state"] == "verified-serving-committed"
                assert commit["candidate"] == str(candidate)
                assert (state / "forward097.attempt").exists()
                assert not (candidate / "DEPLOYED").exists()
                assert "ingress_reopened" not in (state / "forward097.attempt").read_text()
                assert request("/health/readiness") == "200"
                assert sql("select version_num from alembic_version") == "202605310097"
                # Test reconciliation observes live state, never reruns migration or claims receipt.
                assert all(adapter.snapshot(x)["State"]["Running"] for x in adapter.containers)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
            return
        if use_dispatch:
            state = tmp_path / "operator" / "attempt"
            state.mkdir(parents=True, mode=0o700)
            identity = dict(
                sha="d8e147c1b65c0dfda1071edcc7f05efd4f1181e0",
                ci_run=1,
                ci_attempt=1,
                deploy_run=1,
                attempt=1,
                entrypoint_sha256="a" * 64,
            )
            permit = dict(
                identity,
                mode="forward-only-093-to-097",
                source="202605310093",
                target="202605310097",
                not_before=int(time.time()) - 1,
                expires=int(time.time()) + 600,
            )
            permit_path = state / "forward097.permit"
            permit_path.write_text(json.dumps(permit))
            permit_path.chmod(0o600)
            image_id = json.loads(docker("inspect", backend))[0]["Image"]
            policy = dict(
                project=prefix,
                containers=adapter.containers,
                database=db,
                network=network,
                config=str(config),
                image=image_id,
                identity=identity,
            )
            policy_path = tmp_path / "fixture-policy.json"
            policy_path.write_text(json.dumps(policy))
            policy_path.chmod(0o600)
            command = [
                os.sys.executable,
                str(ROOT / "deploy/forward097_isolated_dispatch.py"),
                "--fixture-policy",
                str(policy_path),
                "--fixture-state",
                str(state),
            ]
            policy_path.write_text(json.dumps(dict(policy, image="sha256:" + "0" * 64)))
            rejected = subprocess.run(command, capture_output=True, text=True)
            assert rejected.returncode != 0 and "image mismatch" in rejected.stderr
            assert permit_path.exists() and adapter.snapshot("backend")["State"]["Running"]
            policy_path.write_text(json.dumps(policy))
            if use_dispatch == "migration_failure":
                sql(
                    "CREATE FUNCTION synthetic_ddl_failure() RETURNS event_trigger "
                    "LANGUAGE plpgsql "
                    "AS $$ BEGIN RAISE EXCEPTION 'synthetic migration failure'; END $$"
                )
                sql(
                    "CREATE EVENT TRIGGER synthetic_failure ON ddl_command_start "
                    "WHEN TAG IN ('ALTER TABLE') EXECUTE FUNCTION synthetic_ddl_failure()"
                )
            elif use_dispatch == "activation_failure":
                # Only disposable config: prevents restarted nginx reaching its candidate API.
                config.write_text(
                    config.read_text().replace("http://backend:8000", "http://missing:8000")
                )
            result = subprocess.run(command, capture_output=True, text=True, timeout=100)
            if use_dispatch in ("migration_failure", "activation_failure"):
                assert result.returncode != 0
                assert (state / "forward097.used").exists()
                assert all(
                    not adapter.snapshot(service)["State"]["Running"]
                    for service in adapter.containers
                )
                expected_schema = (
                    "202605310093" if use_dispatch == "migration_failure" else "202605310097"
                )
                assert sql("select version_num from alembic_version") == expected_schema
                assert (
                    "synthetic_dispatch_completed" not in (state / "forward097.attempt").read_text()
                )
                assert subprocess.run(command, capture_output=True).returncode != 0
                return
            assert result.returncode == 0, result.stderr
            assert sql("select version_num from alembic_version") == "202605310097"
            assert (state / "forward097.used").exists() and not permit_path.exists()
            records = [
                json.loads(line)["event"]
                for line in (state / "forward097.attempt").read_text().splitlines()
            ]
            assert records.index("guarded_smoke_verified") < records.index(
                "writers_restarted_after_smoke"
            )
            assert records[-1] == "synthetic_dispatch_completed"
            assert subprocess.run(command, capture_output=True).returncode != 0
            return
        adapter.drain_fixture()
        assert (
            sql(
                "select count(*) from pg_stat_activity "
                "where datname='fixture' and pid<>pg_backend_pid()"
            )
            == "0"
        )

        def actual_guarded_smoke():
            wait_ready(backend)
            assert request("/health/readiness") == "200"
            assert request("/api/v1/projects") == "503"
            assert not adapter.snapshot("celery_worker")["State"]["Running"]
            assert not adapter.snapshot("celery_beat")["State"]["Running"]

        adapter.guarded_restart_fixture(actual_guarded_smoke)
        assert adapter.snapshot("celery_worker")["State"]["Running"]
        assert request("/api/v1/projects") == "503"
        # Controlled reopen only after actual readiness and negative-route probes.
        config.write_text(base)
        docker("exec", nginx, "nginx", "-t")
        docker("exec", nginx, "nginx", "-s", "reload")
        for _ in range(20):
            code = request("/api/v1/projects")
            if code != "503":
                break
            time.sleep(0.1)
        assert code in ("401", "403", "307")
        adapter.stop_warm("celery_beat")
        docker("stop", "--time", "15", worker)
        docker("stop", "--time", "15", backend)
        assert int(sql("select count(*) from activity_log where action='system.shutdown'")) == 2
        assert (
            sql(
                "select count(*) from pg_stat_activity "
                "where datname='fixture' and pid<>pg_backend_pid()"
            )
            == "0"
        )
    finally:
        for name in names:
            if name.endswith("-beat"):
                result = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
                Path("/tmp/garrison-beat-lifecycle-latest.log").write_text(
                    result.stdout + result.stderr
                )
        for name in reversed(names):
            subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)
