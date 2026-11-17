from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

CLI_SESSION_HEADER = "X-Log-CLI-Session"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Remote log access CLI")
    parser.add_argument("--base-url", default=os.getenv("GARRISON_API_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--token", default=os.getenv("GARRISON_LOG_TOKEN"))
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--session-id", default=None)

    subparsers = parser.add_subparsers(dest="command", required=True)

    login_parser = subparsers.add_parser("login", help="Authenticate and retrieve a bearer token")
    login_parser.add_argument("--email", required=True)
    login_parser.add_argument("--password", required=True)
    login_parser.add_argument("--otp")
    login_parser.add_argument("--json", action="store_true")
    login_parser.add_argument("--save-token", type=Path)

    search_parser = subparsers.add_parser("search", help="Search centralized logs")
    search_parser.add_argument("--query")
    search_parser.add_argument("--event-type")
    search_parser.add_argument("--severity")
    search_parser.add_argument("--action")
    search_parser.add_argument("--entity-type")
    search_parser.add_argument("--user-id")
    search_parser.add_argument("--request-id")
    search_parser.add_argument("--session-id-filter")
    search_parser.add_argument("--ip-address")
    search_parser.add_argument("--endpoint")
    search_parser.add_argument("--source-service")
    search_parser.add_argument("--storage-tier")
    search_parser.add_argument("--status-code", type=int)
    search_parser.add_argument("--created-from")
    search_parser.add_argument("--created-to")
    search_parser.add_argument("--limit", type=int, default=50)
    search_parser.add_argument("--offset", type=int, default=0)
    search_parser.add_argument("--json", action="store_true")

    tail_parser = subparsers.add_parser("tail", help="Stream logs in real time")
    tail_parser.add_argument("--query")
    tail_parser.add_argument("--event-type")
    tail_parser.add_argument("--severity")
    tail_parser.add_argument("--action")
    tail_parser.add_argument("--entity-type")
    tail_parser.add_argument("--user-id")
    tail_parser.add_argument("--endpoint")
    tail_parser.add_argument("--source-service")
    tail_parser.add_argument("--storage-tier")
    tail_parser.add_argument("--created-from")
    tail_parser.add_argument("--max-events", type=int, default=0)
    tail_parser.add_argument("--last-event-id", type=UUID)

    return parser


def run(argv: list[str] | None = None, *, client_factory=None, stdout=None) -> int:
    args = build_parser().parse_args(argv)
    stdout = stdout or sys.stdout
    session_id = args.session_id or str(uuid4())

    if args.command == "login":
        with _make_client(args.base_url, client_factory=client_factory) as client:
            return _login(client, args, stdout=stdout, session_id=session_id)

    token = _resolve_token(args)
    if not token:
        raise SystemExit(
            "A bearer token is required. Use --token, --token-file, or GARRISON_LOG_TOKEN."
        )

    with _make_client(args.base_url, token=token, client_factory=client_factory) as client:
        if args.command == "search":
            return _search(client, args, stdout=stdout, session_id=session_id)
        if args.command == "tail":
            return _tail(client, args, stdout=stdout, session_id=session_id)

    raise SystemExit(f"Unsupported command: {args.command}")


def _login(client, args, *, stdout, session_id: str) -> int:
    headers = {CLI_SESSION_HEADER: session_id, "X-Session-ID": session_id}
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": args.email, "password": args.password},
        headers=headers,
    )
    login_response.raise_for_status()
    challenge = login_response.json()
    otp = args.otp or challenge.get("dev_otp")
    if not otp:
        raise SystemExit(
            "OTP required. Re-run with --otp or use an environment where dev_otp is returned."
        )

    verify_response = client.post(
        "/api/v1/auth/verify-otp",
        json={"challenge_id": challenge["challenge_id"], "otp": otp},
        headers=headers,
    )
    verify_response.raise_for_status()
    payload = verify_response.json()

    if args.save_token:
        args.save_token.write_text(payload["access_token"], encoding="utf-8")

    if args.json:
        stdout.write(json.dumps(payload, indent=2))
        stdout.write("\n")
    else:
        stdout.write(f"access_token={payload['access_token']}\n")
        stdout.write(f"user={payload['user']['email']}\n")
    return 0


def _search(client, args, *, stdout, session_id: str) -> int:
    params = {
        "search": args.query,
        "event_type": args.event_type,
        "severity": args.severity,
        "action": args.action,
        "entity_type": args.entity_type,
        "user_id": args.user_id,
        "request_id": args.request_id,
        "session_id": args.session_id_filter,
        "ip_address": args.ip_address,
        "endpoint": args.endpoint,
        "source_service": args.source_service,
        "storage_tier": args.storage_tier,
        "status_code": args.status_code,
        "created_from": args.created_from,
        "created_to": args.created_to,
        "limit": args.limit,
        "offset": args.offset,
    }
    response = client.get(
        "/api/v1/log-events",
        params=_clean_params(params),
        headers=_cli_headers(session_id),
    )
    response.raise_for_status()
    payload = response.json()

    if args.json:
        stdout.write(json.dumps(payload, indent=2))
        stdout.write("\n")
        return 0

    stdout.write(f"total={payload['total']}\n")
    for item in payload["items"]:
        stdout.write(
            f"{item['created_at']} {item['severity']} {item['event_type']} "
            f"{item['action']} {item.get('endpoint') or '-'} {item.get('comments') or ''}\n"
        )
    return 0


def _tail(client, args, *, stdout, session_id: str) -> int:
    params = _clean_params(
        {
            "search": args.query,
            "event_type": args.event_type,
            "severity": args.severity,
            "action": args.action,
            "entity_type": args.entity_type,
            "user_id": args.user_id,
            "endpoint": args.endpoint,
            "source_service": args.source_service,
            "storage_tier": args.storage_tier,
            "created_from": args.created_from,
        }
    )
    seen = 0
    headers = _cli_headers(session_id)
    if args.last_event_id:
        headers["Last-Event-ID"] = str(args.last_event_id)
    with client.stream(
        "GET",
        "/api/v1/log-events/stream",
        params=params,
        headers=headers,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line.removeprefix("data: "))
            stdout.write(json.dumps(payload))
            stdout.write("\n")
            seen += 1
            if args.max_events and seen >= args.max_events:
                break
    return 0


def _resolve_token(args) -> str | None:
    if args.token:
        return args.token
    if args.token_file and args.token_file.exists():
        return args.token_file.read_text(encoding="utf-8").strip() or None
    return None


def _clean_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if value not in {None, ""}}


def _cli_headers(session_id: str) -> dict[str, str]:
    return {CLI_SESSION_HEADER: session_id, "X-Session-ID": session_id}


def _make_client(base_url: str, token: str | None = None, *, client_factory=None):
    if client_factory:
        return client_factory(base_url=base_url, token=token)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=30.0)


if __name__ == "__main__":
    raise SystemExit(run())
