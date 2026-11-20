import importlib.util
import os
import subprocess
import uuid
from pathlib import Path

import pytest

FILE = Path(__file__).resolve().parents[2] / "deploy/maintenance_ingress.py"
spec = importlib.util.spec_from_file_location("maintenance_ingress", FILE)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize(
    "services,sessions",
    [
        ({"backend"}, 0),
        ({"celery_worker"}, 0),
        ({"celery_beat"}, 0),
        ({"nginx"}, 0),
        ({"other_writer"}, 0),
        ({"postgres"}, 1),
        ({"postgres"}, -1),
    ],
)
def test_writer_drain_rejects_unknown_or_live_writers(services, sessions):
    with pytest.raises(ValueError):
        module.verify_drained(services, sessions)


def test_empty_writer_set_and_zero_clients():
    module.verify_drained({"postgres", "redis", "minio"}, 0)


def test_exact_business_config_is_guarded():
    original = (FILE.parent.parent / "nginx/nginx.prod.conf").read_text()
    guarded = module.guarded_config(original)
    assert guarded.count("FORWARD097_MAINTENANCE_GUARD") == 2
    assert original.count("proxy_pass") == guarded.count("proxy_pass")
    assert "/api/v1/(super-admin|support)" in guarded
    with pytest.raises(ValueError):
        module.guarded_config(guarded)


@pytest.mark.skipif(
    os.environ.get("RUN_SYNTHETIC_MAINTENANCE_NGINX") != "1",
    reason="Explicit local Docker ingress verification",
)
def test_real_nginx_blocks_business_and_mutating_requests(tmp_path):
    name = "garrison-maintenance-synthetic-" + uuid.uuid4().hex[:10]
    template = (
        "events {}\nhttp {\nserver {\nlisten 8080;\n"
        "location / { return 200 'synthetic read-only'; }\n}\n}\n"
    )
    config = tmp_path / "nginx.conf"
    config.write_text(module.guarded_config(template))

    def command(*args):
        return subprocess.run(["docker", *args], capture_output=True, text=True, check=True).stdout

    command(
        "run",
        "-d",
        "--name",
        name,
        "--network",
        "none",
        "-v",
        f"{config}:/etc/nginx/nginx.conf:ro",
        "nginx:1.30.7-alpine@sha256:caf4e1e032a20f9c3c5e28fc7f25ffd768ad8677b4975c54193075997b3a97e3",
    )
    try:
        command("exec", name, "nginx", "-t")
        for path in ["/login", "/assets/index-123.js", "/sw.js", "/health/readiness"]:
            assert "synthetic read-only" in command(
                "exec", name, "wget", "-qO-", "http://127.0.0.1:8080" + path
            )
        for path in [
            "/api/v1/projects",
            "/api/v1/auth/login",
            "/api/v1/support",
            "/portal-files/test",
        ]:
            result = subprocess.run(
                ["docker", "exec", name, "wget", "-S", "-O-", "http://127.0.0.1:8080" + path],
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0 and "503" in result.stderr
        result = subprocess.run(
            [
                "docker",
                "exec",
                name,
                "wget",
                "-S",
                "-O-",
                "--post-data=synthetic",
                "http://127.0.0.1:8080/health/readiness",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0 and "503" in result.stderr
    finally:
        command("rm", "-f", "-v", name)
