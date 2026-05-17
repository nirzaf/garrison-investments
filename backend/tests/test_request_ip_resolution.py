from starlette.requests import Request

from app.api.dependencies import get_request_meta
from app.middleware.audit import _client_ip
from app.utils.request import get_client_ip


def build_request(
    *,
    client_host: str,
    forwarded_for: str | None = None,
    real_ip: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("utf-8")))
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode("utf-8")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "raw_path": b"/api/v1/auth/me",
            "scheme": "http",
            "headers": headers,
            "query_string": b"",
            "client": (client_host, 12345),
            "server": ("testserver", 80),
        }
    )


def test_untrusted_peer_cannot_override_client_ip_with_forwarded_headers() -> None:
    request = build_request(
        client_host="198.51.100.10",
        forwarded_for="203.0.113.8",
        real_ip="203.0.113.9",
    )

    assert get_client_ip(request) == "198.51.100.10"
    assert _client_ip(request) == "198.51.100.10"
    assert get_request_meta(request).ip_address == "198.51.100.10"


def test_trusted_proxy_can_forward_client_ip() -> None:
    request = build_request(
        client_host="127.0.0.1",
        forwarded_for="203.0.113.8, 127.0.0.1",
    )

    assert get_client_ip(request) == "203.0.113.8"
    assert _client_ip(request) == "203.0.113.8"
    assert get_request_meta(request).ip_address == "203.0.113.8"