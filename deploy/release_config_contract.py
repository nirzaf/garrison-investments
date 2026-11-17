from __future__ import annotations

import json
import re
import ssl
import subprocess
import time
from collections.abc import Mapping
from ipaddress import IPv4Network, IPv6Network, collapse_addresses, ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

_MAILBOX = re.compile(r"[^@\s<>\x00-\x1f\x7f]+@[^@\s<>\x00-\x1f\x7f]+\.[^@\s<>\x00-\x1f\x7f]+")
_SUPPORT_NAME = "superadmin.garrisons.lk"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def validate_support_email_otp_config(environment: Mapping[str, str]) -> None:
    key = environment.get("SUPPORT_EMAIL_OTP_KEY", "").strip()
    if len(key.encode("utf-8")) < 32 or key in {
        environment.get("SUPPORT_RECOVERY_KEY", "").strip(),
        environment.get("SUPER_ADMIN_OTP_KEY", "").strip(),
    }:
        raise ValueError(
            "Support sign-in requires an independent email OTP key of at least 32 bytes."
        )
    try:
        recipients = json.loads(
            environment.get("SUPPORT_EMAIL_OTP_RECIPIENTS", ""),
            object_pairs_hook=_unique_json_object,
        )
        if not isinstance(recipients, dict) or len(recipients) < 2:
            raise ValueError
        operator_ids: set[UUID] = set()
        mailboxes: set[str] = set()
        for reference, address in recipients.items():
            operator_id = UUID(reference)
            if (
                operator_id.int == 0
                or operator_id in operator_ids
                or not isinstance(address, str)
                or len(address) > 254
                or not _MAILBOX.fullmatch(address)
                or address.casefold() in mailboxes
            ):
                raise ValueError
            operator_ids.add(operator_id)
            mailboxes.add(address.casefold())
    except (TypeError, ValueError, RecursionError):
        raise ValueError(
            "Support sign-in requires valid, distinct OTP mailbox bindings "
            "for at least two operators."
        ) from None


def _validate_support_tls(certificate: Path, key: Path) -> None:
    try:
        # An unattended Nginx start needs an unencrypted key and matching leaf.
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, key, password=lambda: b"")
    except (OSError, ValueError):
        raise ValueError(
            "The support TLS certificate and private key do not load together."
        ) from None
    try:
        checked = subprocess.run(
            [
                "openssl", "x509", "-in", str(certificate), "-noout", "-dates",
                "-ext", "subjectAltName", "-checkhost", _SUPPORT_NAME,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        metadata = checked.stdout
        dates = dict(line.split("=", 1) for line in metadata.splitlines() if "=" in line)
        starts = ssl.cert_time_to_seconds(dates["notBefore"])
        ends = ssl.cert_time_to_seconds(dates["notAfter"])
    except (KeyError, OSError, ValueError, subprocess.SubprocessError):
        raise ValueError("The support TLS certificate metadata could not be verified.") from None
    if not starts <= time.time() < ends:
        raise ValueError("The support TLS certificate is outside its validity period.")
    names = {name.lower() for name in re.findall(r"(?:^|[\s,])DNS:([^,\s]+)", metadata)}
    if names.isdisjoint({_SUPPORT_NAME, "*.garrisons.lk"}):
        raise ValueError(f"The support TLS certificate needs a DNS SAN for {_SUPPORT_NAME}.")
    match_confirmed = metadata.rstrip().endswith(
        f"\nHostname {_SUPPORT_NAME} does match certificate"
    )
    if checked.returncode or not match_confirmed:
        raise ValueError(f"The support TLS certificate must match {_SUPPORT_NAME}.")


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


def validate_support_ingress(
    candidate: Path,
    nginx: Mapping[str, object],
    backend: Mapping[str, object],
    environment: Mapping[str, str],
    files: Mapping[str, Path],
) -> None:
    """Require the flag, private peer, and checked-in virtual host to agree."""
    flag = environment.get("SUPPORT_PORTAL_ENABLED", "false").lower()
    vhost = files.get("/etc/nginx/conf.d/support.conf")
    if flag in {"0", "false", "f", "off", "no", "n"} and vhost is None:
        return
    if flag not in {"1", "true", "t", "on", "yes", "y"} or vhost is None:
        raise ValueError("The support flag and dedicated virtual host must be enabled together.")
    if vhost != candidate / "nginx/support.prod.conf":
        raise ValueError("The support virtual host must come from the tested candidate.")
    mounts = nginx.get("volumes")
    if not isinstance(mounts, list) or not any(
        isinstance(mount, Mapping)
        and mount.get("target") == "/etc/nginx/conf.d/support.conf"
        and mount.get("read_only") is True
        for mount in mounts
    ):
        raise ValueError("The support virtual host must be mounted read-only.")
    command = backend.get("command")
    if (
        not isinstance(command, list)
        or "--no-proxy-headers" not in command
        or "--proxy-headers" in command
    ):
        raise ValueError("The backend must use the socket peer for support ingress checks.")

    networks = nginx.get("networks")
    backend_proxy = networks.get("backend_proxy") if isinstance(networks, Mapping) else None
    configured_peer = (
        backend_proxy.get("ipv4_address") if isinstance(backend_proxy, Mapping) else None
    )
    try:
        peer = ip_address(environment.get("SUPPORT_INGRESS_PEER", ""))
        if peer != ip_address(str(configured_peer)):
            raise ValueError
    except ValueError:
        raise ValueError("Support ingress must pin Nginx's private backend peer.") from None

    tls = "/etc/nginx/ssl/"
    if not all(tls + name in files for name in (
        "support-fullchain.pem", "support-privkey.pem", "support-allowlist.conf"
    )):
        raise ValueError("Support ingress requires its TLS pair and direct-source allowlist.")
    certificate = files[tls + "support-fullchain.pem"]
    private_key = files[tls + "support-privkey.pem"]
    if private_key.stat().st_mode & 0o077:
        raise ValueError("Support ingress TLS key must be private.")
    directives = [
        line.partition("#")[0].strip()
        for line in files[tls + "support-allowlist.conf"].read_text(encoding="utf-8").splitlines()
    ]
    directives = [line for line in directives if line]
    if not directives:
        raise ValueError("Support ingress has no approved direct-source addresses.")
    ipv4: list[IPv4Network] = []
    ipv6: list[IPv6Network] = []
    for directive in directives:
        match = re.fullmatch(r"allow\s+([^\s;]+);", directive)
        try:
            if not match:
                raise ValueError
            network = ip_network(match.group(1))
            if network.prefixlen == 0:
                raise ValueError
        except ValueError:
            raise ValueError("Support allowlist requires bounded, explicit IP networks.") from None
        if isinstance(network, IPv4Network):
            ipv4.append(network)
        else:
            ipv6.append(network)
    if (
        any(network.prefixlen == 0 for network in collapse_addresses(ipv4))
        or any(network.prefixlen == 0 for network in collapse_addresses(ipv6))
    ):
        raise ValueError("The support allowlist must not collectively allow every address.")
    validate_support_email_otp_config(environment)
    validate_support_recovery_delivery_config(environment)
    _validate_support_tls(certificate, private_key)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "t", "on", "yes", "y"}


def _normalized_https_origin(raw: str | None) -> str | None:
    try:
        url = urlsplit((raw or "").strip().rstrip("/"))
    except ValueError:
        return None
    if (
        url.scheme != "https"
        or url.hostname is None
        or url.hostname == _SUPPORT_NAME
        or "*" in url.netloc
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path != ""
    ):
        return None
    return f"https://{url.netloc}"


def validate_support_recovery_delivery_config(environment: Mapping[str, str]) -> None:
    if not _truthy(environment.get("SUPPORT_RECOVERY_DELIVERY_ENABLED")):
        return
    if not _truthy(environment.get("SUPPORT_PORTAL_ENABLED")):
        raise ValueError("Support recovery delivery requires the support portal to be enabled.")
    key = environment.get("SUPPORT_RECOVERY_KEY", "").strip()
    if len(key.encode("utf-8")) < 32 or key in {
        environment.get("SUPPORT_EMAIL_OTP_KEY", "").strip(),
        environment.get("SUPER_ADMIN_OTP_KEY", "").strip(),
    }:
        raise ValueError(
            "Support recovery delivery requires an independent recovery key of at least 32 bytes."
        )
    allowed = {
        parsed
        for item in environment.get("SUPPORT_RECOVERY_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
        if (parsed := _normalized_https_origin(item)) is not None
    }
    raw_items = [
        item for item in environment.get("SUPPORT_RECOVERY_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    ]
    if not raw_items or len(allowed) != len(raw_items):
        raise ValueError("Support recovery delivery requires valid explicit HTTPS origins.")
    frontend_origin = _normalized_https_origin(environment.get("FRONTEND_BASE_URL"))
    if frontend_origin is None or frontend_origin not in allowed:
        raise ValueError(
            "FRONTEND_BASE_URL must match an approved SUPPORT_RECOVERY_ALLOWED_ORIGINS entry."
        )
