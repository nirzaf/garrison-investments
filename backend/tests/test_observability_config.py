from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text())


def test_observability_images_are_digest_pinned_and_ports_are_private() -> None:
    expected_images = {
        "grafana": "grafana/grafana:13.1.1@sha256:",
        "loki": "grafana/loki:3.7.4@sha256:",
        "alloy": "grafana/alloy:v1.18.0@sha256:",
    }
    for filename in ("docker-compose.prod.yml", "docker-compose.staging.yml"):
        services = _compose(filename)["services"]
        for service, prefix in expected_images.items():
            assert services[service]["image"].startswith(prefix)
            assert len(services[service]["image"].split("@sha256:", 1)[1]) == 64
        assert "ports" not in services["loki"]
        assert "ports" not in services["alloy"]

    production = _compose("docker-compose.prod.yml")["services"]
    staging = _compose("docker-compose.staging.yml")["services"]
    assert "ports" not in production["grafana"]
    assert staging["grafana"]["ports"] == ["127.0.0.1:3311:3000"]


def test_grafana_security_database_and_public_urls_are_provisioned() -> None:
    production = _compose("docker-compose.prod.yml")["services"]["grafana"]["environment"]
    staging = _compose("docker-compose.staging.yml")["services"]["grafana"]["environment"]

    for environment in (production, staging):
        assert environment["GF_DATABASE_TYPE"] == "postgres"
        assert environment["GF_DATABASE_NAME"] == "grafana"
        assert environment["GF_USERS_ALLOW_SIGN_UP"] == "false"
        assert environment["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
        assert environment["GF_SECURITY_COOKIE_SECURE"] == "true"
        assert environment["GF_SECURITY_COOKIE_SAMESITE"] == "strict"

    assert production["GF_SERVER_ROOT_URL"] == "https://${GRAFANA_DOMAIN}"
    assert staging["GF_SERVER_ROOT_URL"] == "https://${GRAFANA_DOMAIN}/grafana/"
    assert staging["GF_SERVER_SERVE_FROM_SUB_PATH"] == "true"


def test_grafana_contact_point_transports_preserve_the_operations_route() -> None:
    grafana = ROOT / "observability/grafana"
    alerting = grafana / "provisioning/alerting"
    policy = yaml.safe_load((alerting / "alerts.yml").read_text())["policies"][0]
    smtp = yaml.safe_load((alerting / "contact-point.yml").read_text())["contactPoints"][0]
    usesend_config = yaml.safe_load((grafana / "contact-points/usesend.yml").read_text())
    usesend = usesend_config["contactPoints"][0]

    assert smtp["name"] == usesend["name"] == policy["receiver"]
    smtp_receiver, usesend_receiver = smtp["receivers"][0], usesend["receivers"][0]
    assert smtp_receiver["uid"] == usesend_receiver["uid"]
    assert smtp_receiver["type"] == "email"
    assert usesend_receiver["type"] == "webhook"
    assert usesend_receiver["disableResolveMessage"] is False
    assert usesend_receiver["settings"]["authorization_credentials"] == "$USESEND_API_KEY"
    for filename in ("docker-compose.prod.yml", "docker-compose.staging.yml"):
        volumes = _compose(filename)["services"]["grafana"]["volumes"]
        assert any(
            mount.startswith("${GRAFANA_CONTACT_POINT_FILE:-")
            and mount.endswith(":/etc/grafana/provisioning/alerting/contact-point.yml:ro")
            for mount in volumes
        )


def test_loki_retention_storage_and_alloy_labels_match_policy() -> None:
    loki = yaml.safe_load((ROOT / "observability/loki-config.yml").read_text())
    assert loki["auth_enabled"] is False
    assert loki["schema_config"]["configs"][0]["store"] == "tsdb"
    assert loki["common"]["storage"]["s3"]["bucketnames"] == "loki"
    assert loki["compactor"]["retention_enabled"] is True
    assert loki["limits_config"]["retention_period"] == "336h"
    assert loki["limits_config"]["max_query_lookback"] == "336h"

    alloy = (ROOT / "observability/alloy-config.alloy").read_text()
    for label in ("environment", "compose_project", "service", "container", "severity"):
        assert re.search(rf'target_label\s*=\s*"{label}"', alloy) or re.search(
            rf"^\s*{label}\s*=", alloy, re.MULTILINE
        )
    for forbidden_label in ("request_id", "session_id", "user_id", "endpoint", "task_id"):
        assert f'target_label  = "{forbidden_label}"' not in alloy
        assert f"{forbidden_label} = " not in alloy
    assert 'url = "http://loki:3100/loki/api/v1/push"' in alloy


def test_alloy_applies_second_stage_credential_redaction() -> None:
    alloy = (ROOT / "observability/alloy-config.alloy").read_text()

    assert alloy.count("stage.replace") == 3
    assert alloy.count('replace    = "<redacted>"') == 3
    for token in (
        "access[_-]?token",
        "api[_-]?key",
        "auth(?:orization)?",
        "cookie",
        "jwt",
        "otp",
        "pass(?:word)?",
        "secret",
        "session",
        "token",
        "x[_-]amz[_-](?:credential|signature|security[_-]token)",
    ):
        assert token in alloy
    assert "Bearer" in alloy

    for filename in ("nginx.conf", "nginx.prod.conf"):
        nginx = (ROOT / "nginx" / filename).read_text()
        access_format = next(
            line for line in nginx.splitlines() if line.startswith("log_format portal_access")
        )
        assert "$request_method $uri $server_protocol" in access_format
        assert "$request_uri" not in access_format and "$args" not in access_format
        assert nginx.count("server {\n    access_log /var/log/nginx/access.log portal_access;") == (
            nginx.count("server {")
        )


def test_dashboards_and_alerting_provisioning_are_parseable_and_complete() -> None:
    dashboard_dir = ROOT / "observability/grafana/dashboards"
    dashboards = [json.loads(path.read_text()) for path in sorted(dashboard_dir.glob("*.json"))]
    assert {dashboard["title"] for dashboard in dashboards} == {
        "Garrison Incident Explorer",
        "Garrison Production Logs",
    }
    assert all(dashboard["panels"] for dashboard in dashboards)
    dashboard_queries = json.dumps(dashboards)
    for field in ("request_id", "task_id", "duration_ms", "status_code"):
        assert field in dashboard_queries

    alerts = yaml.safe_load(
        (ROOT / "observability/grafana/provisioning/alerting/alerts.yml").read_text()
    )
    rules = alerts["groups"][0]["rules"]
    assert {rule["uid"] for rule in rules} == {
        "garrison-unhandled-errors",
        "garrison-http-5xx-burst",
        "garrison-celery-retries",
        "garrison-slow-http",
        "garrison-log-pipeline-errors",
    }
    assert all(rule["noDataState"] == "OK" for rule in rules)
    assert all(rule["execErrState"] == "Alerting" for rule in rules)
    assert alerts["policies"][0]["group_interval"] == "5m"


_EXPECTED_ALERT_PREDICATES = {
    "garrison-unhandled-errors": ['message=~"unhandled_request_exception|task_failed"'],
    "garrison-http-5xx-burst": ['message="http_request_completed"', "status_code >= 500"],
    "garrison-celery-retries": ['message="task_retried"', 'service=~"celery_worker|celery_beat"'],
    "garrison-slow-http": [
        'message="http_request_completed"',
        "unwrap duration_ms",
        '__error__=""',
        "by (environment)",
    ],
    "garrison-log-pipeline-errors": ['service=~"loki|alloy"'],
}


def test_alert_rule_queries_match_documented_signals() -> None:
    alerts = yaml.safe_load(
        (ROOT / "observability/grafana/provisioning/alerting/alerts.yml").read_text()
    )
    rules = {rule["uid"]: rule for rule in alerts["groups"][0]["rules"]}
    assert set(rules) == set(_EXPECTED_ALERT_PREDICATES)

    for uid, predicates in _EXPECTED_ALERT_PREDICATES.items():
        expr = rules[uid]["data"][0]["model"]["expr"]
        for predicate in predicates:
            assert predicate in expr, f"{uid} lost predicate {predicate!r}"


def test_grafana_database_initializer_is_idempotent_and_fails_fast() -> None:
    initializer = (ROOT / "observability/postgres/init-grafana-db.sh").read_text()
    assert "--set=ON_ERROR_STOP=1" in initializer
    assert "WHERE NOT EXISTS" in initializer
    assert initializer.count("\\gexec") == 2
    assert "ALTER ROLE grafana" in initializer


def test_staging_domain_is_allowed_and_documented() -> None:
    vite_config = (ROOT / "frontend/vite.config.ts").read_text()
    staging_guide = (ROOT / "STAGING_DEPLOYMENT.md").read_text()
    assert vite_config.count("'erp.garrisons.lk'") == 2
    assert "https://erp.garrisons.lk" in staging_guide
    assert "https://erp.garrisons.lk/grafana/" in staging_guide
