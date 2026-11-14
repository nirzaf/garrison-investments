"""Shared transport and output contract for garrisonctl commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never
from urllib.parse import urlsplit
from uuid import UUID

import httpx

VALIDATION, AUTH, CONFLICT, CONNECTION, FAILED, RECONCILIATION = range(2, 8)
PRIVATE_LIMIT = 64 * 1024
REQUEST_ID = re.compile(r"[a-zA-Z0-9_.:-]{1,128}")


class CLIError(Exception):
    def __init__(
        self,
        message: str,
        code: int = VALIDATION,
        details: Any = None,
        *,
        changed: bool | None = False,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details
        self.changed = changed
        self.data = data


@dataclass
class Result:
    data: Any
    changed: bool | None = False
    outcome: str = "success"


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        # argparse's messages can echo arbitrary command-line input.
        raise CLIError("Invalid command or arguments. See --help.")


class Registry:
    def __init__(self, parser: Parser) -> None:
        self.parser = parser
        self.groups: dict[str, argparse.ArgumentParser] = {"": parser}
        self.subs: dict[str, Any] = {}
        self.commands: dict[str, tuple[argparse.ArgumentParser, dict[str, Any]]] = {}

    def add(
        self,
        name: str,
        handler: Callable[..., Any],
        *,
        permission: str,
        scope: str = "remote",
        mutates: bool = False,
        preview: bool = False,
        approval: bool = False,
        help: str | None = None,
    ) -> argparse.ArgumentParser:
        words = name.split()
        for index, word in enumerate(words):
            parent = " ".join(words[:index])
            key = " ".join(words[: index + 1])
            if parent not in self.subs:
                self.subs[parent] = self.groups[parent].add_subparsers(required=True)
            if key not in self.groups:
                self.groups[key] = self.subs[parent].add_parser(word, help=help)
        leaf = self.groups[name]
        leaf.set_defaults(handler=handler, command_name=name, command_scope=scope)
        self.commands[name] = (
            leaf,
            {
                "command": name,
                "scope": scope,
                "permission": permission,
                "mutates": mutates,
                "supports_preview": preview,
                "approval_required": approval,
            },
        )
        return leaf

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {
                **description,
                "arguments": [
                    {
                        "name": action.option_strings[-1] if action.option_strings else action.dest,
                        "required": action.required,
                    }
                    for action in parser._actions
                    if action.dest
                    not in {
                        "help",
                        "json",
                        "base_url",
                        "environment",
                        "token_file",
                        "session_file",
                    }
                ],
                "argument_choices": [
                    {
                        "required": group.required,
                        "choose_one": [
                            action.option_strings[-1] for action in group._group_actions
                        ],
                    }
                    for group in parser._mutually_exclusive_groups
                ],
            }
            for parser, description in self.commands.values()
        ]


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_private_bytes(path: Path, *, max_bytes: int = PRIVATE_LIMIT) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
    try:
        with os.fdopen(os.open(path, flags), "rb") as file:
            info = os.fstat(file.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
                or info.st_size > max_bytes
            ):
                raise CLIError("Credential file must be private, owned by this user and regular.")
            data = file.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise CLIError("Private input exceeds its size limit.")
            return data
    except OSError:
        raise CLIError("Credential file could not be read securely.") from None


def read_private(path: Path) -> str:
    try:
        return read_private_bytes(path).decode("utf-8")
    except UnicodeError:
        raise CLIError("Credential file must contain UTF-8 text.") from None


def load_json(path: Path, *, max_bytes: int = 8 * 1024 * 1024) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    def invalid_constant(_: str) -> Any:
        raise ValueError("Invalid JSON number.")

    try:
        with path.open("rb") as file:
            data = file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("JSON file is too large.")
        return json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (OSError, ValueError, RecursionError):
        raise CLIError(
            "Expected a readable JSON file with unique keys and finite values."
        ) from None


def normalize_url(raw: str) -> str:
    try:
        url = urlsplit(raw)
        parsed = httpx.URL(raw)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError
        return str(parsed).rstrip("/")
    except (ValueError, httpx.InvalidURL):
        raise CLIError(
            "Use an HTTPS API origin or loopback HTTP, without credentials or paths."
        ) from None


def uuid_arg(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a UUID.") from None


def mode(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    parser.add_argument("--expect", help="plan_sha256 returned by the dry run (required on apply)")


def checked_plan(
    args: argparse.Namespace,
    ctx: Context,
    data: dict[str, Any],
    *,
    bind_actor: bool = False,
) -> dict[str, Any]:
    body = {"target": ctx.base_url, **data}
    if bind_actor:
        body["actor_id"] = ctx.identity()["id"]
    checksum = sha256_json(body)
    if getattr(args, "apply", False):
        if not getattr(args, "expect", None):
            raise CLIError("Apply requires --expect from the matching dry run.")
        if args.expect != checksum:
            raise CLIError("The plan or current state changed. Run a fresh dry run.", CONFLICT)
    return {**body, "plan_sha256": checksum}


class Context:
    def __init__(
        self,
        client: httpx.Client,
        base_url: str,
        environment: str,
        session: Any = None,
    ) -> None:
        self.client = client
        self.base_url = base_url
        self.environment = environment
        self.session = session
        self.request_id: str | None = None
        self.last_headers = httpx.Headers()
        self.secrets: set[str] = set()
        self.write_request_id: str | None = None
        self.write_attempted = False
        self._identity: dict[str, Any] | None = None

    def identity(self) -> dict[str, Any]:
        if self._identity is None:
            identity = self.request("GET", "/api/v1/auth/me")
            if not isinstance(identity, dict) or not isinstance(identity.get("id"), str):
                raise CLIError("The API returned an invalid identity.", CONNECTION)
            self._identity = identity
        return self._identity

    def _headers(self, auth: bool, supplied: Any) -> dict[str, str]:
        headers = dict(supplied or {})
        if auth:
            token = self.session.bearer(self) if self.session else None
            if not token:
                raise CLIError("Authenticate first or supply a short-lived bearer token.", AUTH)
            self.secrets.add(token)
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _check(self, response: httpx.Response) -> None:
        self.last_headers = response.headers
        reference = response.headers.get("x-request-id", "")
        self.request_id = reference if REQUEST_ID.fullmatch(reference) else None
        status = response.status_code
        if 200 <= status < 300:
            return
        code, message = {
            400: (VALIDATION, "The API rejected the request."),
            401: (AUTH, "Authentication failed or the session expired."),
            403: (AUTH, "The API denied this operation."),
            404: (CONFLICT, "The requested record or endpoint is unavailable."),
            409: (CONFLICT, "The API reported a state conflict."),
            412: (CONFLICT, "The expected state no longer matches."),
            413: (VALIDATION, "The API rejected the upload size."),
            422: (VALIDATION, "One or more request fields are invalid."),
            429: (CONNECTION, "The API rate limit was reached."),
        }.get(status, (CONNECTION, "The API returned an unexpected HTTP status."))
        details: dict[str, Any] = {"http_status": status}
        if not response.is_stream_consumed:
            raise CLIError(message, code, details)
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            payload = None
        if isinstance(payload, dict):
            error_code = payload.get("error_code")
            if isinstance(error_code, str) and re.fullmatch(r"[A-Z][A-Z_0-9]{0,79}", error_code):
                details["error_code"] = error_code
            issues = payload.get("errors")
            if isinstance(issues, list):
                details["fields"] = [
                    {key: item[key] for key in ("loc", "field", "type", "row") if key in item}
                    for item in issues[:100]
                    if isinstance(item, dict)
                ]
        raise CLIError(message, code, details)

    def request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = True,
        write: bool = False,
        **kwargs: Any,
    ) -> Any:
        self._check_path(path)
        headers = self._headers(auth, kwargs.pop("headers", None))
        self.write_attempted |= write
        try:
            response = self.client.request(method, path, headers=headers, **kwargs)
            if write:
                reference = response.headers.get("x-request-id", "")
                self.write_request_id = reference if REQUEST_ID.fullmatch(reference) else None
            self._check(response)
        except httpx.HTTPError:
            raise CLIError(
                "Connection to the API failed.",
                CONNECTION,
                changed=None if write else False,
            ) from None
        except CLIError as error:
            if write and error.details and error.details.get("http_status", 0) >= 500:
                error.changed = None
            raise
        if not response.content:
            return None
        if "json" not in response.headers.get("content-type", ""):
            return response.text
        try:
            return response.json()
        except (ValueError, UnicodeError):
            raise CLIError(
                "The API returned invalid JSON.",
                CONNECTION,
                changed=None if write else False,
            ) from None

    @contextmanager
    def stream(self, method: str, path: str, *, auth: bool = True, **kwargs: Any) -> Iterator:
        self._check_path(path)
        headers = self._headers(auth, kwargs.pop("headers", None))
        try:
            with self.client.stream(method, path, headers=headers, **kwargs) as response:
                self._check(response)
                yield response
        except httpx.HTTPError:
            raise CLIError("Connection to the API stream failed.", CONNECTION) from None

    @staticmethod
    def _check_path(path: str) -> None:
        if not path.startswith(("/api/v1/", "/health")) or path.startswith("//"):
            raise CLIError("Unsupported API path.")


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def verified(ctx: Context, read: Callable[[], Any], check: Callable[[Any], bool]) -> Result:
    try:
        observed = read()
    except CLIError:
        raise CLIError(
            "The API accepted the operation, but readback failed.",
            FAILED,
            changed=None,
            data={"verification": "unavailable"},
        ) from None
    if not check(observed):
        raise CLIError(
            "The API accepted the operation, but readback differed.",
            FAILED,
            changed=None,
            data={"verification": "mismatch"},
        )
    return Result(observed, changed=True)
