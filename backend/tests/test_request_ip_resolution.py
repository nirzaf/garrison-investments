import pytest
from starlette.requests import Request

from app.api.dependencies import get_request_meta
from app.config import Settings
from app.middleware.audit import _client_ip
from app.utils.request import get_client_ip, is_trusted_proxy


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


def test_spoofed_leftmost_forwarded_entry_is_ignored() -> None:
    # The caller prepends a fake hop; nginx appends the real peer on the right.
    request = build_request(
        client_host="127.0.0.1",
        forwarded_for="1.2.3.4, 203.0.113.8, 127.0.0.1",
    )

    assert get_client_ip(request) == "203.0.113.8"
    assert _client_ip(request) == "203.0.113.8"
    assert get_request_meta(request).ip_address == "203.0.113.8"


def test_real_ip_wins_over_a_spoofable_forwarded_chain() -> None:
    request = build_request(
        client_host="127.0.0.1",
        forwarded_for="1.2.3.4, 5.6.7.8",
        real_ip="203.0.113.8",
    )

    assert get_client_ip(request) == "203.0.113.8"


def test_all_trusted_forwarded_hops_fall_back_to_the_peer() -> None:
    request = build_request(
        client_host="::1",
        forwarded_for="127.0.0.1, ::1",
    )

    assert get_client_ip(request) == "::1"


def test_empty_forwarded_header_falls_back_to_the_peer() -> None:
    request = build_request(client_host="127.0.0.1", forwarded_for="  ,  ")

    assert get_client_ip(request) == "127.0.0.1"


def test_forwarded_addresses_must_be_valid_ips() -> None:
    request = build_request(client_host="127.0.0.1", forwarded_for="203.0.113.8", real_ip="invalid")
    assert get_client_ip(request) == "203.0.113.8"
    malformed_chain = build_request(client_host="127.0.0.1", forwarded_for="203.0.113.8, invalid")
    assert get_client_ip(malformed_chain) == "127.0.0.1"


def use_trusted_proxies(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setattr("app.utils.request.get_settings", lambda: Settings(trusted_proxy_ips=value))


def test_trusted_proxy_subnet_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    use_trusted_proxies(monkeypatch, "127.0.0.1,::1,172.16.0.0/12")
    request = build_request(
        client_host="172.18.0.3",
        forwarded_for="1.2.3.4, 203.0.113.8",
        real_ip="203.0.113.8",
    )

    assert get_client_ip(request) == "203.0.113.8"


def test_trusted_subnet_hops_are_skipped_right_to_left(monkeypatch: pytest.MonkeyPatch) -> None:
    use_trusted_proxies(monkeypatch, "172.16.0.0/12")
    request = build_request(
        client_host="172.18.0.3",
        forwarded_for="1.2.3.4, 203.0.113.8, 172.18.0.9",
    )

    assert get_client_ip(request) == "203.0.113.8"


def test_peer_outside_the_trusted_subnet_cannot_forward(monkeypatch: pytest.MonkeyPatch) -> None:
    use_trusted_proxies(monkeypatch, "172.16.0.0/12")
    request = build_request(
        client_host="192.168.1.50",
        forwarded_for="203.0.113.8",
        real_ip="203.0.113.9",
    )

    assert get_client_ip(request) == "192.168.1.50"


def test_malformed_trust_entries_never_widen_the_boundary() -> None:
    assert is_trusted_proxy("172.18.0.3", ["not-an-ip", "172.16.0.0/99", ""]) is False
    assert is_trusted_proxy(None, ["172.16.0.0/12"]) is False
    assert is_trusted_proxy("172.18.0.3", ["172.16.0.0/12"]) is True
    # An IPv4 peer is never matched by an IPv6 entry, and vice versa.
    assert is_trusted_proxy("172.18.0.3", ["::1/128"]) is False
    assert is_trusted_proxy("::1", ["127.0.0.1"]) is False
