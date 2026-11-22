from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "deploy/postgres19_maintenance_contract.py"
SPEC = importlib.util.spec_from_file_location("postgres19_maintenance_contract", CONTRACT_PATH)
assert SPEC is not None and SPEC.loader is not None
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)

PG19 = CONTRACT.POSTGRES_19_IMAGE


def compose_config(*, target: bool) -> dict:
    old = not target
    db_volume = "pgdata" if old else "pgdata19"
    db_volume_name = CONTRACT.POSTGRES_18_VOLUME if old else CONTRACT.POSTGRES_19_VOLUME
    postgres_image = "postgres:18.6-alpine" if old else PG19
    init_source = (
        "/opt/garrison-portal/releases/prior/observability/postgres/init-grafana-db.sh"
        if old
        else "/opt/garrison-portal/releases/candidate/observability/postgres/init-grafana-db.sh"
    )
    return {
        "networks": {"default": {"name": "garrison-portal_default"}},
        "volumes": {
            db_volume: {"name": db_volume_name},
            "redisdata": {"name": "garrison-portal_redisdata"},
            "miniodata": {"name": "garrison-portal_miniodata"},
        },
        "services": {
            "postgres": {
                "image": postgres_image,
                "environment": {"POSTGRES_DB": "garrison_portal"},
                "volumes": [
                    {
                        "type": "volume",
                        "source": db_volume,
                        "target": CONTRACT.POSTGRES_DATA_TARGET,
                        "read_only": False,
                    }
                ],
                "healthcheck": {"test": ["pg_isready"]},
            },
            "grafana_db_init": {
                "image": postgres_image,
                "environment": (
                    {
                        "PGHOST": "postgres",
                        "BACKUP_ENCRYPTION_PASSWORD": "fixture-legacy-secret",
                    }
                    if old
                    else {
                        "PGHOST": "postgres",
                        "BACKUP_ENCRYPTION_KEY_HOST_FILE": "/run/private/backup-key",
                    }
                ),
                "volumes": [
                    {
                        "type": "bind",
                        "source": init_source,
                        "target": "/init/init-grafana-db.sh",
                        "read_only": True,
                    }
                ],
            },
            "redis": {"image": "redis:7-alpine"},
            "minio": {"image": "example/minio:fixed"},
            "loki_minio_init": {
                "image": "example/mc:fixed",
                "environment": (
                    {
                        "LOKI_BUCKET": "logs",
                        "BACKUP_ENCRYPTION_PASSWORD": "fixture-legacy-secret",
                    }
                    if old
                    else {
                        "LOKI_BUCKET": "logs",
                        "BACKUP_ENCRYPTION_KEY_HOST_FILE": "/run/private/backup-key",
                    }
                ),
            },
        },
    }


def test_postgres19_transition_accepts_only_new_pinned_volume_and_init_client() -> None:
    CONTRACT.validate_compose_transition(compose_config(target=False), compose_config(target=True))


def test_postgres19_transition_accepts_unchanged_file_based_backup_secret() -> None:
    previous = compose_config(target=False)
    candidate = compose_config(target=True)
    previous["services"]["grafana_db_init"]["environment"] = {
        "PGHOST": "postgres",
        "BACKUP_ENCRYPTION_KEY_HOST_FILE": "/run/private/backup-key",
    }

    CONTRACT.validate_compose_transition(previous, candidate)


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_target_image",
        "reuse_source_volume",
        "change_network",
        "change_redis",
        "change_minio",
        "change_pg_settings",
        "change_grafana_init_settings",
        "change_loki_init_settings",
        "retain_legacy_backup_secret",
        "remove_backup_secret_file",
        "change_volume_target",
        "invalid_volume_definition",
    ],
)
def test_postgres19_transition_rejects_unrelated_or_unsafe_changes(mutation: str) -> None:
    previous = compose_config(target=False)
    candidate = compose_config(target=True)
    if mutation == "wrong_target_image":
        candidate["services"]["postgres"]["image"] = "postgres:19.0-alpine3.24"
    elif mutation == "reuse_source_volume":
        candidate["services"]["postgres"]["volumes"][0]["source"] = "pgdata"
    elif mutation == "change_network":
        candidate["networks"]["default"]["name"] = "other_default"
    elif mutation == "change_redis":
        candidate["services"]["redis"]["image"] = "redis:8-alpine"
    elif mutation == "change_minio":
        candidate["services"]["minio"]["image"] = "example/minio:new"
    elif mutation == "change_pg_settings":
        candidate["services"]["postgres"]["environment"]["POSTGRES_DB"] = "other"
    elif mutation == "change_grafana_init_settings":
        candidate["services"]["grafana_db_init"]["environment"]["PGHOST"] = "other"
    elif mutation == "change_loki_init_settings":
        candidate["services"]["loki_minio_init"]["environment"]["LOKI_BUCKET"] = "other"
    elif mutation == "retain_legacy_backup_secret":
        candidate["services"]["grafana_db_init"]["environment"] = {
            "PGHOST": "postgres",
            "BACKUP_ENCRYPTION_PASSWORD": "fixture-legacy-secret",
        }
    elif mutation == "remove_backup_secret_file":
        candidate["services"]["grafana_db_init"]["environment"].pop(
            "BACKUP_ENCRYPTION_KEY_HOST_FILE"
        )
    elif mutation == "change_volume_target":
        candidate["services"]["postgres"]["volumes"][0]["target"] = "/var/lib/postgresql/data"
    elif mutation == "invalid_volume_definition":
        candidate["volumes"]["pgdata19"] = "not-a-volume-map"
    with pytest.raises(CONTRACT.MaintenanceContractError):
        CONTRACT.validate_compose_transition(previous, candidate)


def live_container() -> dict:
    return {
        "Config": {
            "Image": PG19,
            "Labels": {
                "com.docker.compose.project": "garrison-portal",
                "com.docker.compose.service": "postgres",
            },
        },
        "State": {"Running": True},
        "Mounts": [
            {
                "Type": "volume",
                "Name": CONTRACT.POSTGRES_19_VOLUME,
                "Destination": CONTRACT.POSTGRES_DATA_TARGET,
            }
        ],
    }


def test_postgres19_live_target_requires_preserved_source_drained_writers_and_matching_schema() -> (
    None
):
    CONTRACT.validate_live_target(
        container=live_container(),
        source_volume_exists=True,
        target_volume_exists=True,
        server_version_num="190000",
        schema_head="202605310098",
        candidate_heads="202605310098",
        running_services={"postgres", "redis", "minio", "loki"},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"source_volume_exists": False},
        {"target_volume_exists": False},
        {"server_version_num": "180006"},
        {"schema_head": "202605310097"},
        {"candidate_heads": "202605310099"},
        {"running_services": {"nginx", "postgres"}},
        {"container": {"Config": {"Image": "postgres:19.0-alpine3.24"}}},
    ],
)
def test_postgres19_live_target_fails_closed(changes: dict) -> None:
    args = {
        "container": live_container(),
        "source_volume_exists": True,
        "target_volume_exists": True,
        "server_version_num": "190000",
        "schema_head": "202605310098",
        "candidate_heads": "202605310098",
        "running_services": {"postgres", "redis", "minio"},
    }
    args.update(deepcopy(changes))
    with pytest.raises(CONTRACT.MaintenanceContractError):
        CONTRACT.validate_live_target(**args)
