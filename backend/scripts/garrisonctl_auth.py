"""Interactive OTP authentication and private, origin-bound CLI sessions."""

from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import os
import stat
import tempfile
import time
import warnings
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx

from scripts.garrisonctl_common import (
    AUTH,
    CONNECTION,
    FAILED,
    CLIError,
    Context,
    Registry,
    Result,
    read_private,
    sha256_json,
)


def prompt_secret(label: str) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(label)
    except (OSError, EOFError, getpass.GetPassWarning):
        raise CLIError("A private terminal is required for secure input.", AUTH) from None
    if not value or len(value) > 256:
        raise CLIError("Invalid secret length.")
    return value


class Session:
    def __init__(self, args: argparse.Namespace, stack: ExitStack, origin: str) -> None:
        self.args = args
        self.stack = stack
        self.origin = origin
        self.path = args.session_file or (
            Path.home() / ".config" / "garrisonctl" / (sha256_json(origin) + ".json")
        )
        self.external = args.token_file is not None or bool(os.getenv("GARRISON_ACCESS_TOKEN"))
        self.record: dict[str, Any] | None = None
        self.locked = False

    def lock(self) -> None:
        if self.locked:
            return
        try:
            parent = self.path.parent
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = parent.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
            ):
                raise CLIError("Use an owner-only directory for CLI sessions.", AUTH)
            lock = self.path.with_name(self.path.name + ".lock")
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            self.stack.callback(os.close, fd)
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
            ):
                raise CLIError("The session lock file is unsafe.", AUTH)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise CLIError("The CLI session is unavailable or in use.", AUTH) from None
        self.locked = True

    def load(self) -> dict[str, Any] | None:
        self.lock()
        if self.record is None and (self.path.exists() or self.path.is_symlink()):
            try:
                record = json.loads(read_private(self.path))
                if (
                    not isinstance(record, dict)
                    or record.get("origin") != self.origin
                    or not isinstance(record.get("access"), str)
                    or not isinstance(record.get("refresh"), str)
                    or type(record.get("expires")) is not int
                ):
                    raise ValueError
            except (ValueError, RecursionError):
                raise CLIError("Invalid session file or API origin mismatch.", AUTH) from None
            self.record = record
        return self.record

    def save(self, ctx: Context, payload: Any) -> dict[str, Any]:
        refresh = next(
            (cookie.value for cookie in ctx.client.cookies.jar if cookie.name == "refresh_token"),
            None,
        )
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("access_token"), str)
            or type(payload.get("expires_in_seconds")) is not int
            or payload["expires_in_seconds"] < 1
            or not refresh
        ):
            raise CLIError("The API returned an incomplete session.", CONNECTION, changed=None)
        ctx.secrets.update({payload["access_token"], refresh})
        self.record = {
            "origin": self.origin,
            "access": payload["access_token"],
            "refresh": refresh,
            "expires": int(time.time()) + payload["expires_in_seconds"],
        }
        self.lock()
        pending = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent,
                prefix=".session-",
                mode="w",
                delete=False,
            ) as file:
                pending = Path(file.name)
                json.dump(self.record, file)
                file.flush()
                os.fsync(file.fileno())
            pending.replace(self.path)
        except OSError:
            raise CLIError(
                "The authenticated session could not be saved.",
                FAILED,
                changed=None,
            ) from None
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)
        user = payload.get("user")
        if not isinstance(user, dict):
            raise CLIError("The API returned an invalid identity.", CONNECTION, changed=None)
        return user

    def bearer(self, ctx: Context) -> str:
        if self.external:
            token = (
                read_private(self.args.token_file).strip()
                if self.args.token_file is not None
                else os.environ["GARRISON_ACCESS_TOKEN"].strip()
            )
            if not token or any(char.isspace() or not char.isascii() for char in token):
                raise CLIError("Invalid access token input.", AUTH)
            return token
        record = self.load()
        if record is None:
            raise CLIError("Authenticate first or supply a short-lived bearer token.", AUTH)
        if record["expires"] <= time.time() + 15:
            self.refresh(ctx, record)
        assert self.record is not None
        return str(self.record["access"])

    def refresh(self, ctx: Context, record: dict[str, Any]) -> None:
        ctx.client.cookies.clear()
        ctx.secrets.add(record["refresh"])
        payload = ctx.request(
            "POST",
            "/api/v1/auth/refresh",
            auth=False,
            headers={"Cookie": "refresh_token=" + record["refresh"]},
        )
        self.save(ctx, payload)


def login(args: argparse.Namespace, ctx: Context) -> Result:
    if ctx.session.external:
        raise CLIError("Login uses an origin-bound CLI session.")
    if args.dry_run:
        return Result(
            {"email": args.email, "action": "request OTP and save a private session"},
            outcome="preview",
        )
    if ctx.session.load() is not None:
        raise CLIError("A session file exists. Sign out before signing in again.", AUTH)
    password = prompt_secret("Password: ")
    ctx.secrets.add(password)
    challenge = ctx.request(
        "POST",
        "/api/v1/auth/login",
        auth=False,
        json={"email": args.email, "password": password},
    )
    if not isinstance(challenge, dict) or not isinstance(challenge.get("challenge_id"), str):
        raise CLIError("The API returned an invalid login challenge.", CONNECTION)
    otp = prompt_secret("One-time code: ")
    ctx.secrets.add(otp)
    payload = ctx.request(
        "POST",
        "/api/v1/auth/verify-otp",
        auth=False,
        write=True,
        json={"challenge_id": challenge["challenge_id"], "otp": otp},
    )
    return Result(ctx.session.save(ctx, payload), changed=True)


def logout(args: argparse.Namespace, ctx: Context) -> Result:
    if ctx.session.external:
        raise CLIError("Logout requires the original CLI refresh session.", AUTH)
    if args.dry_run:
        path = ctx.session.path
        return Result(
            {"session_file_present": path.is_file() and not path.is_symlink()}, outcome="preview"
        )
    record = ctx.session.load()
    if record is None:
        return Result({"signed_out": True})
    if not args.local_only:
        ctx.secrets.add(record["refresh"])
        ctx.request(
            "POST",
            "/api/v1/auth/logout",
            auth=False,
            write=True,
            headers={"Cookie": "refresh_token=" + record["refresh"]},
        )
    try:
        ctx.session.path.unlink()
    except OSError:
        raise CLIError("Could not remove the CLI session file.", FAILED, changed=None) from None
    ctx.client.cookies = httpx.Cookies()
    return Result(
        {"signed_out": True, "server_logout_requested": not args.local_only}, changed=True
    )


def register(registry: Registry) -> None:
    parser = registry.add(
        "auth login",
        login,
        permission="password and OTP",
        mutates=True,
        preview=True,
        help="Sign in with a password and OTP",
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--dry-run", action="store_true")
    registry.add(
        "auth whoami",
        lambda args, ctx: ctx.identity(),
        permission="authenticated",
        help="Inspect the current identity and permissions",
    )
    parser = registry.add(
        "auth logout",
        logout,
        permission="CLI refresh session",
        mutates=True,
        preview=True,
        help="Revoke a CLI session and remove its local file",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--local-only", action="store_true", help="Remove an unusable local session"
    )
