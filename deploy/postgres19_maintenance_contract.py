"""Fail-closed checks for the one-shot PostgreSQL 18 to 19 maintenance release."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

POSTGRES_19_IMAGE = (
    "postgres:19.0-alpine3.24@sha256:"
    "8b0ff4cdf221f0c53d7fcda681d3b461be725c492cd881c5ec9c0ad25023f188"
)
POSTGRES_DATA_TARGET = "/var/lib/postgresql"
POSTGRES_18_VOLUME = "garrison-portal_pgdata"
POSTGRES_19_VOLUME = "garrison-portal_pgdata19"
_LEGACY_BACKUP_SECRET_ENV = "BACKUP_ENCRYPTION_PASSWORD"
_BACKUP_SECRET_FILE_ENV = "BACKUP_ENCRYPTION_KEY_HOST_FILE"


class MaintenanceContractError(ValueError):
    """The observed release transition is outside the reviewed PostgreSQL upgrade."""


def _volume_map(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get("volumes")
    if not isinstance(value, Mapping):
        raise MaintenanceContractError("Compose volume definitions are missing.")
    return value


def _named_volume(volumes: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = volumes.get(name)
    if not isinstance(value, Mapping):
        raise MaintenanceContractError(f"Compose volume {name} is invalid.")
    return value


def _service(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    services = config.get("services")
    if not isinstance(services, Mapping) or not isinstance(services.get(name), Mapping):
        raise MaintenanceContractError(f"Compose service {name} is missing.")
    return services[name]


def _mounts(service: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = service.get("volumes")
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise MaintenanceContractError("PostgreSQL volume mounts are invalid.")
    return value


def _check_data_mount(service: Mapping[str, Any], *, source: str) -> None:
    matches = [mount for mount in _mounts(service) if mount.get("target") == POSTGRES_DATA_TARGET]
    if (
        len(matches) != 1
        or matches[0].get("type") != "volume"
        or matches[0].get("source") != source
        or matches[0].get("read_only") is True
    ):
        raise MaintenanceContractError("PostgreSQL must use the expected versioned data volume.")


def _without(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in keys}


def _secret_aware_service_settings(service: Mapping[str, Any]) -> dict[str, Any]:
    """Permit only the exact production backup-secret env migration."""
    settings = _without(service, "image", "volumes")
    environment = settings.get("environment")
    if not isinstance(environment, Mapping):
        raise MaintenanceContractError("Service environment is invalid.")
    return {
        **settings,
        "environment": {
            key: value
            for key, value in environment.items()
            if key not in {_LEGACY_BACKUP_SECRET_ENV, _BACKUP_SECRET_FILE_ENV}
        },
    }


def _validate_backup_secret_transition(
    old_service: Mapping[str, Any], new_service: Mapping[str, Any]
) -> None:
    old_environment = old_service.get("environment")
    new_environment = new_service.get("environment")
    if not isinstance(old_environment, Mapping) or not isinstance(new_environment, Mapping):
        raise MaintenanceContractError("Service environment is invalid.")

    new_file = new_environment.get(_BACKUP_SECRET_FILE_ENV)
    if (
        not isinstance(new_file, str)
        or not new_file.strip()
        or _LEGACY_BACKUP_SECRET_ENV in new_environment
    ):
        raise MaintenanceContractError(
            "The candidate must use only the protected backup-secret file setting."
        )

    old_legacy = old_environment.get(_LEGACY_BACKUP_SECRET_ENV)
    old_file = old_environment.get(_BACKUP_SECRET_FILE_ENV)
    if old_legacy is not None:
        if old_file is not None or not str(old_legacy).strip():
            raise MaintenanceContractError("The previous backup-secret configuration is invalid.")
    elif not isinstance(old_file, str) or not old_file.strip():
        raise MaintenanceContractError(
            "The previous release has no recognized backup-secret configuration."
        )
    elif old_file != new_file:
        raise MaintenanceContractError("The host backup-secret file path cannot change here.")


def validate_compose_transition(previous: Mapping[str, Any], candidate: Mapping[str, Any]) -> None:
    """Accept only the intended PG volume/image transition and PG19 init client."""
    if previous.get("networks") != candidate.get("networks"):
        raise MaintenanceContractError("PostgreSQL maintenance cannot change networks.")

    old_volumes = _volume_map(previous)
    new_volumes = _volume_map(candidate)
    if set(old_volumes) - {"pgdata"} != set(new_volumes) - {"pgdata19"}:
        raise MaintenanceContractError("PostgreSQL maintenance changed unrelated volumes.")
    if _named_volume(old_volumes, "pgdata").get("name") != POSTGRES_18_VOLUME:
        raise MaintenanceContractError("The PostgreSQL 18 source volume identity changed.")
    if _named_volume(new_volumes, "pgdata19").get("name") != POSTGRES_19_VOLUME:
        raise MaintenanceContractError("The PostgreSQL 19 target volume identity changed.")
    for name in set(old_volumes) - {"pgdata"}:
        if old_volumes[name] != new_volumes[name]:
            raise MaintenanceContractError(f"Unrelated volume {name} changed.")

    old_db = _service(previous, "postgres")
    new_db = _service(candidate, "postgres")
    if not str(old_db.get("image", "")).startswith("postgres:18"):
        raise MaintenanceContractError("The source database image is not PostgreSQL 18.")
    if new_db.get("image") != POSTGRES_19_IMAGE:
        raise MaintenanceContractError(
            "The target database image is not the pinned PostgreSQL 19 image."
        )
    _check_data_mount(old_db, source="pgdata")
    _check_data_mount(new_db, source="pgdata19")
    if _without(old_db, "image", "volumes") != _without(new_db, "image", "volumes"):
        raise MaintenanceContractError(
            "PostgreSQL service settings changed outside the major upgrade."
        )

    old_init = _service(previous, "grafana_db_init")
    new_init = _service(candidate, "grafana_db_init")
    if not str(old_init.get("image", "")).startswith("postgres:18"):
        raise MaintenanceContractError("The source Grafana initializer is not using PostgreSQL 18.")
    if new_init.get("image") != POSTGRES_19_IMAGE:
        raise MaintenanceContractError(
            "The Grafana initializer must use the pinned PostgreSQL 19 image."
        )
    old_init_mounts = _mounts(old_init)
    new_init_mounts = _mounts(new_init)
    if len(old_init_mounts) != 1 or len(new_init_mounts) != 1:
        raise MaintenanceContractError("The Grafana initializer mount set changed.")
    for mount in (old_init_mounts[0], new_init_mounts[0]):
        source = str(mount.get("source", ""))
        if (
            mount.get("type") != "bind"
            or mount.get("target") != "/init/init-grafana-db.sh"
            or not source.removeprefix("./").endswith("observability/postgres/init-grafana-db.sh")
            or mount.get("read_only") is not True
        ):
            raise MaintenanceContractError("The Grafana initializer script mount is invalid.")
    _validate_backup_secret_transition(old_init, new_init)
    if _secret_aware_service_settings(old_init) != _secret_aware_service_settings(new_init):
        raise MaintenanceContractError(
            "Grafana initialization settings changed outside the client upgrade."
        )

    for name in ("redis", "minio"):
        if _service(previous, name) != _service(candidate, name):
            raise MaintenanceContractError(f"Unrelated stateful service {name} changed.")

    old_loki_init = _service(previous, "loki_minio_init")
    new_loki_init = _service(candidate, "loki_minio_init")
    _validate_backup_secret_transition(old_loki_init, new_loki_init)
    if (
        old_loki_init.get("image") != new_loki_init.get("image")
        or old_loki_init.get("volumes") != new_loki_init.get("volumes")
        or _secret_aware_service_settings(old_loki_init)
        != _secret_aware_service_settings(new_loki_init)
    ):
        raise MaintenanceContractError(
            "Loki initializer settings changed outside the backup-secret migration."
        )


def validate_live_target(
    *,
    container: Mapping[str, Any],
    source_volume_exists: bool,
    target_volume_exists: bool,
    server_version_num: str,
    schema_head: str,
    candidate_heads: str,
    running_services: set[str],
) -> None:
    """Require a restored target, preserved source, exact schema, and drained writers."""
    config = container.get("Config")
    state = container.get("State")
    labels = config.get("Labels") if isinstance(config, Mapping) else None
    mounts = container.get("Mounts")
    if (
        not isinstance(config, Mapping)
        or not isinstance(state, Mapping)
        or not isinstance(labels, Mapping)
        or not isinstance(mounts, list)
        or not state.get("Running")
        or labels.get("com.docker.compose.project") != "garrison-portal"
        or labels.get("com.docker.compose.service") != "postgres"
        or config.get("Image") != POSTGRES_19_IMAGE
    ):
        raise MaintenanceContractError("The live PostgreSQL 19 container identity is invalid.")
    if not source_volume_exists or not target_volume_exists:
        raise MaintenanceContractError("Both PostgreSQL volumes must exist before activation.")
    data_mounts = [
        mount
        for mount in mounts
        if isinstance(mount, Mapping) and mount.get("Destination") == POSTGRES_DATA_TARGET
    ]
    if (
        len(data_mounts) != 1
        or data_mounts[0].get("Type") != "volume"
        or data_mounts[0].get("Name") != POSTGRES_19_VOLUME
    ):
        raise MaintenanceContractError(
            "The live PostgreSQL 19 container is not using the fresh target volume."
        )
    if not server_version_num.startswith("19"):
        raise MaintenanceContractError("The live PostgreSQL server is not version 19.")
    if not schema_head or schema_head != candidate_heads:
        raise MaintenanceContractError(
            "The restored PostgreSQL 19 schema must match candidate Alembic heads."
        )
    if running_services.intersection(
        {"nginx", "backend", "celery_worker", "celery_beat", "grafana"}
    ):
        raise MaintenanceContractError("Ingress, application writers, and Grafana must be stopped.")
