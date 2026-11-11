import re
from ipaddress import ip_address, ip_network

from fastapi import Request

from app.config import get_settings

CORRELATION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def is_trusted_proxy(candidate: str | None, trusted: list[str]) -> bool:
    """Match a peer against TRUSTED_PROXY_IPS entries, which may be IPs or CIDR subnets.

    Subnet entries let a deployment trust its own proxy container without pinning a
    Docker-assigned address that changes on every recreate.
    """
    if not candidate:
        return False
    try:
        address = ip_address(candidate)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if "/" in entry:
                if address in ip_network(entry, strict=False):
                    return True
            elif address == ip_address(entry):
                return True
        except ValueError:
            # A malformed entry must never widen the trust boundary.
            continue
    return False


def get_client_ip(request: Request) -> str | None:
    """Resolve the true edge client IP for audit and rate-limit records.

    Only a direct peer listed in ``TRUSTED_PROXY_IPS`` may speak for the client.
    ``X-Real-IP`` wins because nginx sets it to ``$remote_addr`` — the socket peer it
    actually saw (see nginx/nginx.prod.conf). ``X-Forwarded-For`` is walked
    **right-to-left**, skipping trusted hops: the leftmost entries are supplied by the
    caller and are trivially spoofable, while the rightmost untrusted entry was appended
    by a proxy we control.
    """
    direct_ip = request.client.host if request.client else None
    if not direct_ip:
        return None
    trusted = get_settings().trusted_proxy_ips_list
    if not is_trusted_proxy(direct_ip, trusted):
        return direct_ip

    real_ip = _valid_ip(request.headers.get("X-Real-IP", "").strip())
    if real_ip is not None:
        return real_ip

    forwarded_for = request.headers.get("X-Forwarded-For") or ""
    for hop in reversed([entry.strip() for entry in forwarded_for.split(",")]):
        if not hop:
            continue
        address = _valid_ip(hop)
        if address is None:
            return direct_ip
        if not is_trusted_proxy(address, trusted):
            return address
    return direct_ip


def _valid_ip(value: str) -> str | None:
    try:
        return str(ip_address(value))
    except ValueError:
        return None


def trusted_correlation_ids(request: Request, trusted: list[str]) -> tuple[str | None, str | None]:
    if not request.client or not is_trusted_proxy(request.client.host, trusted):
        return None, None
    request_id = request.headers.get("X-Request-ID", "")
    session_id = request.headers.get("X-Session-ID", "")
    return (
        request_id if CORRELATION_ID_PATTERN.fullmatch(request_id) else None,
        session_id if CORRELATION_ID_PATTERN.fullmatch(session_id) else None,
    )
