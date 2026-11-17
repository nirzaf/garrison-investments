"""Terminal administration for the Garrisons portal."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any, TextIO

import httpx

from app.utils.redaction import redact_payload
from scripts import (
    garrisonctl_access,
    garrisonctl_auth,
    garrisonctl_data,
    garrisonctl_hr,
    garrisonctl_ops,
    garrisonctl_support,
)
from scripts.garrisonctl_common import (
    CONNECTION,
    FAILED,
    CLIError,
    Context,
    Parser,
    Registry,
    Result,
    json_safe,
    normalize_url,
)

VERSION = "1.0.0"
DEFAULT_URL = "http://127.0.0.1:8000"
POLICY = "/api/v1/finance/policy"


def validate_policy(args: argparse.Namespace, _: Context) -> dict[str, Any]:
    return garrisonctl_ops.read_policy_proposal(args.file).model_dump(mode="json")


def health(_: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    result = ctx.request("GET", "/health/readiness", auth=False)
    if (
        not isinstance(result, dict)
        or result.get("status") != "ready"
        or result.get("database") != "connected"
    ):
        raise CLIError("The portal readiness response did not confirm database access.", CONNECTION)
    return {"status": result["status"], "database": result["database"]}


def add_global_options(parser: argparse.ArgumentParser) -> None:
    options = parser.add_argument_group("connection and output")
    options.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    options.add_argument(
        "--base-url",
        default=argparse.SUPPRESS,
        help="HTTPS origin or local HTTP. Defaults to GARRISON_API_BASE_URL.",
    )
    options.add_argument("--session-file", type=Path, default=argparse.SUPPRESS)
    options.add_argument("--token-file", type=Path, default=argparse.SUPPRESS)
    options.add_argument(
        "--environment",
        default=argparse.SUPPRESS,
        help="Operator-supplied label for the response envelope",
    )


def build_parser() -> Parser:
    parser = Parser(prog="garrisonctl", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    registry = Registry(parser)
    registry.add(
        "capabilities",
        lambda a, c: {
            "version": VERSION,
            "commands": registry.capabilities(),
        },
        permission="none",
        scope="local",
        help="List supported operations and arguments",
    )
    garrisonctl_auth.register(registry)
    garrisonctl_access.register(registry)
    garrisonctl_data.register(registry)
    garrisonctl_ops.register(registry)
    garrisonctl_hr.register(registry)
    garrisonctl_support.register(registry)
    registry.add("health check", health, permission="public readiness")
    for command in ("config", "finance policy"):
        registry.add(
            f"{command} show", lambda a, c: c.request("GET", POLICY), permission="authenticated"
        )
        leaf = registry.add(
            f"{command} validate", validate_policy, permission="none", scope="local"
        )
        leaf.add_argument("--file", type=Path, required=True)
    registry.add(
        "finance policy reconciliation",
        lambda a, c: c.request(
            "GET",
            f"{POLICY}/reconciliation",
        ),
        permission="financial:view",
    )
    # Keep globals discoverable and usable before or after subcommands.
    for group in registry.groups.values():
        add_global_options(group)
    return parser


def public_envelope(envelope: dict[str, Any], secrets: set[str]) -> dict[str, Any]:
    known = sorted(secrets, key=len, reverse=True)

    def clean_text(value: str) -> str:
        for secret in known:
            value = value.replace(secret, "[redacted]")
        return redact_payload(value)

    def sanitize(value: Any, depth: int = 0) -> Any:
        if depth >= 24:
            return "[redacted-depth-limit]"
        if isinstance(value, dict):
            return {
                clean_text(str(key)): (
                    item
                    if key == "must_change_password" and isinstance(item, bool)
                    else "[redacted]"
                    if redact_payload(None, key=key) == "[redacted]"
                    else sanitize(item, depth + 1)
                )
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [sanitize(item, depth + 1) for item in value]
        if isinstance(value, str):
            return clean_text(value)
        return redact_payload(json_safe(value))

    return sanitize(envelope)


def run(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    json_output = "--json" in argv
    args = None
    context = None
    environment = "unspecified"
    try:
        args = build_parser().parse_args(argv)
        json_output = getattr(args, "json", False)
        default_url = (
            garrisonctl_support.ORIGIN
            if args.command_name.startswith("support ")
            else os.getenv("GARRISON_API_BASE_URL") or DEFAULT_URL
        )
        base_url = normalize_url(getattr(args, "base_url", None) or default_url)
        environment = (
            getattr(args, "environment", None)
            or os.getenv("GARRISON_ENVIRONMENT")
            or (
                "local"
                if args.command_scope == "local"
                else "host"
                if args.command_scope == "host"
                else base_url
            )
        )
        args.token_file = getattr(args, "token_file", None)
        args.session_file = getattr(args, "session_file", None)
        with ExitStack() as stack:
            client = stack.enter_context(
                httpx.Client(
                    base_url=base_url,
                    timeout=15,
                    follow_redirects=False,
                    transport=transport,
                    trust_env=False,
                )
            )
            session = garrisonctl_auth.Session(args, stack, base_url)
            context = Context(client, base_url, environment, session)
            result = args.handler(args, context)
            if not isinstance(result, Result):
                result = Result(result)
        errors: list[Any] = []
        code = 0
    except CLIError as error:
        result = Result(error.data, error.changed, "error")
        errors = [{"message": str(error), "details": error.details}]
        code = error.code
    except KeyboardInterrupt:
        result = Result(None, None, "error")
        errors = [{"message": "Interrupted. Check server state before retrying a write."}]
        code = FAILED
    except (OSError, KeyError, TypeError, ValueError, httpx.HTTPError):
        result = Result(None, None if context and context.write_attempted else False, "error")
        errors = [{"message": "The command could not read its inputs or verify its response."}]
        code = FAILED
    envelope = public_envelope(
        {
            "format_version": 1,
            "command": getattr(args, "command_name", None),
            "environment": environment,
            "outcome": result.outcome,
            "changed": result.changed,
            "data": result.data,
            "errors": errors,
            "request_id": (context.write_request_id or context.request_id) if context else None,
        },
        context.secrets if context else set(),
    )
    if json_output:
        print(json.dumps(envelope, ensure_ascii=False, allow_nan=False), file=stdout)
    elif errors:
        print(envelope["errors"][0]["message"], file=stderr)
        if result.data is not None:
            print(json.dumps(envelope["data"], ensure_ascii=False, indent=2), file=stdout)
    else:
        print(json.dumps(envelope["data"], ensure_ascii=False, indent=2), file=stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(run())
