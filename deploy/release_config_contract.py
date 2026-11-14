from __future__ import annotations

from collections.abc import Mapping


def validate_pinned_service_environment(
    service_name: str,
    service: object,
    expected_environment: Mapping[str, str],
) -> dict[str, str]:
    """Require the normalized Compose service environment to retain pinned values."""
    if not isinstance(service, Mapping):
        raise ValueError(f"Effective Compose service {service_name} is invalid")

    raw_environment = service.get("environment") or {}
    environment: dict[str, str] = {}
    if isinstance(raw_environment, Mapping):
        for key, value in raw_environment.items():
            if not isinstance(key, str) or not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"Effective Compose environment for {service_name} is invalid")
            environment[key] = str(value).strip().strip("\"'")
    elif isinstance(raw_environment, list):
        for entry in raw_environment:
            if not isinstance(entry, str) or "=" not in entry:
                raise ValueError(f"Effective Compose environment for {service_name} is invalid")
            key, value = entry.split("=", 1)
            environment[key] = value.strip().strip("\"'")
    else:
        raise ValueError(f"Effective Compose environment for {service_name} is invalid")

    missing = sorted(set(expected_environment) - set(environment))
    mismatched = sorted(
        key
        for key, expected in expected_environment.items()
        if key in environment and environment[key] != expected
    )
    if missing or mismatched:
        details = []
        if missing:
            details.append(f"missing keys: {', '.join(missing)}")
        if mismatched:
            details.append(f"mismatched keys: {', '.join(mismatched)}")
        raise ValueError(
            f"Service {service_name} does not receive the pinned production environment "
            f"({'; '.join(details)})"
        )
    return environment
