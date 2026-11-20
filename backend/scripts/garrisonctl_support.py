"""Commands authenticated by the dedicated Super Admin passkey session."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import webbrowser
from base64 import urlsafe_b64decode, urlsafe_b64encode
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from secrets import token_hex, token_urlsafe
from typing import TYPE_CHECKING, Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ValidationError

from scripts.garrisonctl_common import (
    AUTH,
    CONFLICT,
    CONNECTION,
    FAILED,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    mode,
    read_private,
    write_private_bytes,
)

if TYPE_CHECKING:
    from app.api.v1.support import RegistrationStatus
    from app.schemas.support_cases import SupportCaseRead

ORIGIN = "https://superadmin.garrisons.lk"
_API = "/api/v1/support"
_SECRET = re.compile(r"[A-Za-z0-9_-]{43}")
_ADAPTERS = (
    "permission-explanation",
    "navigation",
    "request-summary",
    "project-list",
    "project-detail-summary",
)


def _require_origin(ctx: Context) -> None:
    if ctx.base_url != ORIGIN or ctx.session.args.token_file is not None:
        raise CLIError("Use the dedicated technical HTTPS origin and support session.", AUTH)


def _headers(ctx: Context, token: str, csrf: str) -> dict[str, str]:
    ctx.secrets.update({token, csrf})
    return {
        "Origin": ORIGIN,
        "Cookie": f"__Host-garrison-support={token}; __Host-garrison-support-csrf={csrf}",
        "X-Support-CSRF": csrf,
    }


def _session_headers(ctx: Context) -> dict[str, str]:
    _require_origin(ctx)
    ctx.session.lock()
    path = ctx.session.path
    if not path.exists():
        raise CLIError("Sign in to the technical CLI first.", AUTH)
    try:
        record = json.loads(read_private(path))
        if not isinstance(record, dict) or record.get("origin") != ORIGIN:
            raise ValueError
        token, csrf = record["support_token"], record["support_csrf"]
        if not all(isinstance(value, str) and _SECRET.fullmatch(value) for value in (token, csrf)):
            raise ValueError
    except (ValueError, KeyError):
        raise CLIError("The technical session file is invalid.", AUTH) from None
    return _headers(ctx, token, csrf)


def _require_private_destination(path: Path) -> None:
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise CLIError("Output requires a private, owned directory.")
    if path.exists() or path.is_symlink():
        raise CLIError("Select a new private output file.")


def _private_output(path: Path, payload: Any) -> None:
    _require_private_destination(path)
    write_private_bytes(path, (json.dumps(payload, ensure_ascii=False) + "\n").encode())


def _private_terminal():
    try:
        return open("/dev/tty", "r+", encoding="utf-8", buffering=1)
    except OSError:
        raise CLIError("CLI sign-in requires an interactive terminal.", AUTH) from None


def login(args: argparse.Namespace, ctx: Context) -> Result:
    _require_origin(ctx)
    if not args.apply:
        return Result(
            {"action": "Open passkey and email verification for the technical CLI"},
            outcome="preview",
        )
    ctx.session.lock()
    path = ctx.session.path
    if path.exists() or path.is_symlink():
        raise CLIError("Sign out or select a new technical session file before signing in.", AUTH)
    token, csrf, code = token_urlsafe(32), token_urlsafe(32), token_hex(6)
    ctx.secrets.update({token, csrf, code})
    with _private_terminal() as tty:
        reply = ctx.request(
            "POST",
            _API + "/auth/cli/start",
            auth=False,
            write=True,
            headers={"Origin": ORIGIN},
            json={
                "operator_id": str(args.operator),
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "csrf_hash": hashlib.sha256(csrf.encode()).hexdigest(),
                "code_hash": hashlib.sha256(code.encode()).hexdigest(),
            },
        )
        reference = UUID(reply["challenge_id"])
        url = f"{ORIGIN}/#cli={reference}"
        tty.write(f"Approve this sign-in on {ORIGIN}. Terminal pairing code: {code}\n")
        if not webbrowser.open(url, new=2):
            tty.write(f"Open this approval page in Chrome: {url}\n")
        tty.write("After browser approval, press Enter.\n")
        if not tty.readline():
            raise CLIError("CLI sign-in was interrupted.", AUTH)
    headers = _headers(ctx, token, csrf)
    profile = ctx.request("GET", _API + "/me", auth=False, headers=headers)
    if not isinstance(profile, dict) or profile.get("operator_id") != str(args.operator):
        raise CLIError("The technical sign-in identity could not be verified.", AUTH)
    try:
        _private_output(path, {"origin": ORIGIN, "support_token": token, "support_csrf": csrf})
    except (CLIError, OSError):
        # A successfully approved but unsaved session should not remain active.
        try:
            ctx.request("POST", _API + "/auth/logout", auth=False, write=True, headers=headers)
        except CLIError:
            pass
        raise CLIError("The approved technical session could not be saved.", AUTH) from None
    return Result({"authenticated": True, "expires_at": profile.get("expires_at")}, changed=True)


def logout(args: argparse.Namespace, ctx: Context) -> Result:
    _require_origin(ctx)
    if not args.apply:
        return Result({"action": "Revoke the technical CLI session"}, outcome="preview")
    headers = _session_headers(ctx)
    try:
        ctx.request("POST", _API + "/auth/logout", auth=False, write=True, headers=headers)
    except CLIError as error:
        if not error.details or error.details.get("http_status") != 401:
            raise
    ctx.session.path.unlink(missing_ok=True)
    return Result({"authenticated": False}, changed=True)


def _read(ctx: Context, path: str, output: Path, **query: Any) -> Result:
    payload = ctx.request(
        "GET",
        _API + path,
        auth=False,
        headers=_session_headers(ctx),
        params={key: value for key, value in query.items() if value is not None},
    )
    _private_output(output, payload)
    return Result({"written_to_private_file": True})


def _read_overview(args: argparse.Namespace, ctx: Context) -> Result:
    if args.domain not in {"projects", "inventory"} and (
        args.case is not None or args.project is not None
    ):
        raise CLIError(
            "Case and project scope options apply only to projects and inventory overviews."
        )
    if args.project is not None and args.case is None:
        raise CLIError("Project scoping requires a linked --case.")
    path = "/overview" if args.domain == "company" else f"/overview/{args.domain}"
    return _read(
        ctx,
        path,
        args.output,
        case_id=str(args.case) if args.case is not None else None,
        project_id=str(args.project) if args.project is not None else None,
    )


def _search_accounts(args: argparse.Namespace, ctx: Context) -> Result:
    path = f"/cases/{args.case}/accounts"
    if args.selector_file is None:
        return _read(ctx, path, args.output)
    from app.services.support_directory import SupportAccountSelector

    try:
        selector = SupportAccountSelector.model_validate_json(read_private(args.selector_file))
    except ValidationError:
        raise CLIError("The private account selector is invalid.") from None
    ctx.secrets.add(selector.value)
    payload = ctx.request(
        "POST", _API + path + "/search", auth=False, headers=_session_headers(ctx),
        json=selector.model_dump(mode="json"),
    )
    _private_output(args.output, payload)
    return Result({"written_to_private_file": True})


def _list_cases(args: argparse.Namespace, ctx: Context) -> Result:
    cursor = None
    if args.cursor_from:
        cursor = json.loads(read_private(args.cursor_from)).get("next_cursor")
        if not isinstance(cursor, str) or not 0 < len(cursor) <= 256:
            raise CLIError("The private page has no usable continuation cursor.")
    return _read(ctx, "/cases", args.output, limit=args.limit, cursor=cursor)


def _read_window(args: argparse.Namespace, ctx: Context, source: str) -> Result:
    now = datetime.now(UTC)
    return _read(
        ctx,
        f"/cases/{args.case}/{source}",
        args.output,
        limit=args.limit,
        request_id=getattr(args, "request", None),
        started_at=(now - timedelta(hours=args.hours)).isoformat(),
        ended_at=now.isoformat(),
    )


def _follow_logs(args: argparse.Namespace, ctx: Context) -> Result:
    from app.services.support_request_logs import SupportRequestEvent
    from scripts import health_monitor, release_contract

    if not 1 <= args.seconds <= 60 or not 1 <= args.max_events <= 100:
        raise CLIError("Follow accepts 1 through 100 events and 1 through 60 seconds.")
    headers = _session_headers(ctx)
    cursor: UUID | None = None
    if args.cursor_from:
        try:
            previous = json.loads(read_private(args.cursor_from))
            if previous["case_id"] != str(args.case) or previous["request_id"] != args.request:
                raise ValueError
            cursor = UUID(previous["last_event_id"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise CLIError("The private receipt has no cursor for this case request.") from exc
        headers["Last-Event-ID"] = str(cursor)
    events: list[dict[str, Any]] = []
    connected = False
    finished = "disconnected"
    closed_frame = False
    try:
        with (
            health_monitor.deadline(args.seconds),
            ctx.stream(
                "GET",
                f"{_API}/cases/{args.case}/logs/stream",
                auth=False,
                headers=headers,
                params={"request_id": args.request, "hours": args.hours},
                timeout=args.seconds + 1,
            ) as response,
        ):
            if response.headers.get("content-type", "").split(";", 1)[0] != "text/event-stream":
                raise CLIError("The API returned an invalid evidence stream.", CONNECTION)
            connected = True
            for line in response.iter_lines():
                if not line:
                    closed_frame = False
                elif line == "event: closed":
                    closed_frame = True
                elif line.startswith("data: "):
                    if len(line) > 16_384:
                        raise CLIError("The API returned an oversized evidence event.", CONNECTION)
                    event = release_contract.strict_json(line.removeprefix("data: ").encode())
                    if closed_frame:
                        reason = event.get("reason") if isinstance(event, dict) else None
                        if reason not in (
                            "session_ended", "access_ended", "time_limit", "unavailable"
                        ):
                            raise CLIError("The API returned an invalid stream status.", CONNECTION)
                        finished = reason
                        break
                    item = SupportRequestEvent.model_validate(event)
                    cursor = item.id
                    events.append(item.model_dump(mode="json"))
                    if len(events) >= args.max_events:
                        finished = "event_limit"
                        break
    except TimeoutError:
        if not connected:
            raise CLIError(
                "The evidence stream did not connect before the deadline.", CONNECTION
            ) from None
        finished = "time_limit"
    except (ValidationError, release_contract.ContractError):
        raise CLIError("The API returned a malformed evidence event.", CONNECTION) from None
    _private_output(args.output, {
        "case_id": str(args.case),
        "request_id": args.request,
        "last_event_id": str(cursor) if cursor is not None else None,
        "items": events,
        "finished_by": finished,
    })
    return Result({"written_to_private_file": True, "finished_by": finished})


def _end_view(args: argparse.Namespace, ctx: Context) -> Result:
    if not args.apply:
        return Result({"action": "End the approved support view"}, outcome="preview")
    ctx.request(
        "POST",
        f"{_API}/views/{args.view}/end",
        auth=False,
        write=True,
        headers=_session_headers(ctx),
    )
    return Result({"ended": True}, changed=True)


def _profile(ctx: Context, headers: dict[str, str]) -> str:
    profile = ctx.request("GET", _API + "/me", auth=False, headers=headers)
    if not isinstance(profile, dict) or not isinstance(profile.get("operator_id"), str):
        raise CLIError("The technical operator identity could not be verified.", AUTH)
    return str(UUID(profile["operator_id"]))


def _mutation_plan(
    args: argparse.Namespace,
    ctx: Context,
    *,
    actor: str,
    path: str,
    body: dict[str, Any],
    revision: int | None = None,
) -> dict[str, Any]:
    if args.dry_run:
        intent = uuid4()
    else:
        if args.plan is None:
            raise CLIError("Apply requires the private file from the matching dry run.", CONFLICT)
        try:
            previous = json.loads(read_private(args.plan))
            if previous["plan_sha256"] != args.expect:
                raise ValueError
            intent = UUID(previous["intent"])
        except (KeyError, TypeError, ValueError):
            raise CLIError("The private plan and supplied digest do not agree.", CONFLICT) from None
    return checked_plan(
        args,
        ctx,
        {
            "intent": str(intent),
            "actor": actor,
            "path": path,
            "body": body,
            "expected_case_revision": revision,
        },
    )


def _case_revision(ctx: Context, case_id: UUID, headers: dict[str, str]) -> SupportCaseRead:
    from app.schemas.support_cases import SupportCaseRead

    current = SupportCaseRead.model_validate(
        ctx.request("GET", f"{_API}/cases/{case_id}", auth=False, headers=headers)
    )
    if current.id != case_id:
        raise CLIError("The backend returned another case.", FAILED)
    return current


def _preview(args: argparse.Namespace, plan: dict[str, Any]) -> Result:
    _private_output(args.output, plan)
    return Result(
        {"plan_sha256": plan["plan_sha256"], "written_to_private_file": True}, outcome="preview"
    )


def _save_receipt(args: argparse.Namespace, receipt: Any) -> Result:
    try:
        _private_output(args.output, receipt)
    except (CLIError, OSError):
        raise CLIError(
            "The API accepted the operation, but the private receipt could not be written.",
            FAILED,
            changed=None,
        ) from None
    return Result({"written_to_private_file": True}, changed=True)


def _change_case(args: argparse.Namespace, ctx: Context, *, transition: bool) -> Result:
    from app.schemas.support_cases import SupportCaseCreate, SupportCaseRead, SupportCaseTransition

    _require_private_destination(args.output)
    schema = SupportCaseTransition if transition else SupportCaseCreate
    body = schema.model_validate_json(read_private(args.input)).model_dump(mode="json")
    headers = _session_headers(ctx)
    actor = _profile(ctx, headers)
    current = _case_revision(ctx, args.case, headers) if transition else None
    if current is not None:
        path = f"{_API}/cases/{current.id}/transitions"
        if {"open": "investigating", "investigating": "mitigated"}.get(current.status) != body[
            "status"
        ]:
            raise CLIError("The case cannot make that transition from its current state.", CONFLICT)
        headers["If-Match"] = f'"{current.revision}"'
    else:
        path = f"{_API}/cases"
    plan = _mutation_plan(
        args,
        ctx,
        actor=actor,
        path=path,
        body=body,
        revision=current.revision if current else None,
    )
    if args.dry_run:
        return _preview(args, plan)
    reply = ctx.request("POST", path, auth=False, write=True, headers=headers, json=body)
    try:
        accepted = SupportCaseRead.model_validate(reply)
        observed = _case_revision(ctx, accepted.id, headers)
        expected = accepted == observed
        if current:
            expected = expected and (
                accepted.id == current.id
                and accepted.status == body["status"]
                and accepted.revision == current.revision + 1
            )
        else:
            expected = expected and (
                accepted.owner_id == UUID(actor)
                and accepted.revision == 1
                and accepted.status == "open"
                and all(getattr(accepted, field) == value for field, value in body.items())
            )
    except (CLIError, ValueError):
        expected = False
    if not expected:
        raise CLIError(
            "The API accepted the case change, but readback differed.", FAILED, changed=None
        )
    return _save_receipt(args, reply)


def _propose(
    args: argparse.Namespace,
    ctx: Context,
    *,
    endpoint: str,
    schema: Callable[[], type[BaseModel]],
    receipt_id: str,
    case_revision: bool = False,
    business: bool = False,
) -> Result:
    from app.schemas.support_business_actions import BusinessActionRead
    from app.schemas.support_case_actions import CaseActionRead

    _require_private_destination(args.output)
    model = schema()
    body = model.model_validate_json(read_private(args.input)).model_dump(mode="json")
    headers = _session_headers(ctx)
    actor = _profile(ctx, headers)
    path = _API + endpoint
    revision = _case_revision(ctx, args.case, headers).revision if case_revision else None
    if revision is not None:
        headers["If-Match"] = f'"{revision}"'
    plan = _mutation_plan(args, ctx, actor=actor, path=path, body=body, revision=revision)
    if args.dry_run:
        return _preview(args, plan)
    if business:
        headers["Idempotency-Key"] = str(uuid5(NAMESPACE_URL, plan["plan_sha256"]))
    else:
        # The case and custody proposal endpoints have no client replay key.
        submitted = args.plan.with_name(args.plan.name + ".submitted")
        _private_output(submitted, {"plan_sha256": plan["plan_sha256"]})
    reply = ctx.request("POST", path, auth=False, write=True, headers=headers, json=body)
    try:
        UUID(reply[receipt_id])
        if business:
            BusinessActionRead.model_validate(reply)
        elif case_revision:
            CaseActionRead.model_validate(reply)
        expected = {key: value for key, value in body.items() if key != "reason"}
        if business or case_revision:
            expected["case_id"] = str(args.case)
        if revision is not None:
            expected["case_revision"] = revision
        if not all(reply.get(key) == value for key, value in expected.items()):
            raise ValueError
    except (AttributeError, KeyError, TypeError, ValueError):
        raise CLIError(
            "The API returned an unexpected proposal receipt.", FAILED, changed=None
        ) from None
    return _save_receipt(args, reply)


def _mutation_arguments(leaf: argparse.ArgumentParser, *, case: bool = False) -> None:
    if case:
        leaf.add_argument("--case", type=UUID, required=True)
    leaf.add_argument("--input", type=Path, required=True)
    leaf.add_argument("--plan", type=Path, help="Private dry-run output (required on apply)")
    leaf.add_argument("--output", type=Path, required=True)
    mode(leaf)


def _evidence_command(args: argparse.Namespace, ctx: Context, operation: str) -> Result:
    from app.schemas.support_evidence_export import (
        MAX_EXPORT_BYTES,
        SupportEvidenceExportCreate,
        SupportEvidenceExportRead,
    )

    _require_private_destination(args.output)
    headers = _session_headers(ctx)
    actor = _profile(ctx, headers)
    if operation == "propose":
        requested = SupportEvidenceExportCreate.model_validate_json(read_private(args.input))
        path = f"{_API}/cases/{args.case}/exports"
        body = requested.model_dump(mode="json")
    else:
        expected = SupportEvidenceExportRead.model_validate_json(read_private(args.input))
        path = f"{_API}/cases/{expected.case_id}/exports/{expected.id}/{operation}"
        body = expected.model_dump(mode="json", exclude={"approved_at", "downloaded_at"})
    plan = _mutation_plan(args, ctx, actor=actor, path=path, body=body)
    if args.dry_run:
        return _preview(args, plan)
    submitted = args.plan.with_name(args.plan.name + ".submitted")
    _require_private_destination(submitted)
    if operation == "propose":
        _private_output(submitted, {"plan_sha256": plan["plan_sha256"]})
        reply = ctx.request("POST", path, auth=False, write=True, headers=headers, json=body)
        accepted = SupportEvidenceExportRead.model_validate(reply)
        if (
            accepted.case_id != args.case or accepted.filters != requested.filters
            or accepted.reason != requested.reason or accepted.approved_at is not None
        ):
            raise CLIError("The returned evidence filters did not match the request.", FAILED)
        return _save_receipt(args, accepted.model_dump(mode="json"))

    options = ctx.request("POST", path + "/options", auth=False, headers=headers, json={})
    if not isinstance(options, dict):
        raise CLIError("The API did not return an evidence passkey challenge.", AUTH)
    live = SupportEvidenceExportRead.model_validate(options.get("export"))
    if live.model_dump(mode="json", exclude={"approved_at", "downloaded_at"}) != body:
        raise CLIError("The live evidence receipt changed. Open a new reviewed export.", CONFLICT)
    proof = _proof_handoff(ctx, headers, str(UUID(options["challenge_id"])))
    proof["expected_sha256"] = expected.sha256
    _private_output(submitted, {"plan_sha256": plan["plan_sha256"]})
    if operation == "review":
        reply = ctx.request("POST", path, auth=False, write=True, headers=headers, json=proof)
        accepted = SupportEvidenceExportRead.model_validate(reply)
        if (
            accepted.approved_at is None or accepted.downloaded_at is not None
            or accepted.model_dump(mode="json", exclude={"approved_at", "downloaded_at"}) != body
        ):
            raise CLIError("The API returned an unexpected export approval.", FAILED, changed=None)
        return _save_receipt(args, accepted.model_dump(mode="json"))
    content = bytearray()
    try:
        with ctx.stream("POST", path, auth=False, headers=headers, json=proof) as response:
            if (
                response.headers.get("Content-Type", "").split(";", 1)[0] != "text/csv"
                or response.headers.get("X-Support-Export-Sha256") != expected.sha256
            ):
                raise ValueError
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > MAX_EXPORT_BYTES:
                    raise ValueError
        if hashlib.sha256(content).hexdigest() != expected.sha256:
            raise ValueError
    except CLIError as error:
        status = (error.details or {}).get("http_status")
        if isinstance(status, int) and 400 <= status < 500:
            raise
        raise CLIError(
            "The download was interrupted and may have been consumed.", FAILED, changed=None
        ) from None
    except ValueError:
        raise CLIError(
            "The export was consumed, but the received file failed verification.",
            FAILED, changed=True,
        ) from None
    try:
        write_private_bytes(args.output, bytes(content))
    except OSError:
        raise CLIError(
            "The export was consumed, but the private file could not be saved.",
            FAILED, changed=True,
        ) from None
    return Result({
        "written_to_private_file": True, "sha256": expected.sha256, "truncated": expected.truncated,
    }, changed=True)


def _proof_handoff(ctx: Context, headers: dict[str, str], original_proof: str) -> dict[str, Any]:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from app.api.v1.support import SupportVerifyRequest

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encoded = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    code = token_hex(6)
    ctx.secrets.add(code)
    with _private_terminal() as tty:
        request = ctx.request(
            "POST",
            f"{_API}/auth/cli-proof/start",
            auth=False,
            write=True,
            headers=headers,
            json={
                "proof_id": original_proof,
                "pairing_hash": hashlib.sha256(code.encode()).hexdigest(),
                "encryption_key": urlsafe_b64encode(encoded).decode().rstrip("="),
            },
        )
        reference = str(UUID(request["reference"]))
        url = f"{ORIGIN}/#proof={reference}"
        tty.write(f"Terminal action pairing code: {code}\n")
        if not webbrowser.open(url, new=2):
            tty.write(f"Open this approval page in Chrome: {url}\n")
        tty.write("After the browser confirms the proof was sent, press Enter.\n")
        if not tty.readline():
            raise CLIError("CLI passkey approval was interrupted.", AUTH)
    reply = ctx.request(
        "POST",
        f"{_API}/auth/cli-proof/take",
        auth=False,
        headers=headers,
        json={"reference": reference},
    )
    try:
        sealed = reply["sealed"]
        if not isinstance(sealed, str) or not re.fullmatch(r"[A-Za-z0-9_-]{380,32768}", sealed):
            raise ValueError
        envelope = urlsafe_b64decode(sealed + "=" * (-len(sealed) % 4))
        wrapped_key, nonce, ciphertext = envelope[:256], envelope[256:268], envelope[268:]
        secret = key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        proof = SupportVerifyRequest.model_validate_json(
            AESGCM(secret).decrypt(nonce, ciphertext, reference.encode())
        ).model_dump(mode="json")
        if proof["challenge_id"] != original_proof:
            raise ValueError
        return proof
    except (InvalidTag, KeyError, TypeError, ValueError):
        raise CLIError("The sealed passkey response could not be verified.", AUTH) from None


def _decision_plan(family: str, stage: str, raw: str) -> tuple[str, str, str, dict[str, Any]]:
    from app.api.v1.support import GrantChangeRead, RegistrationProposalRead, SuspensionRead
    from app.schemas.support_business_actions import BusinessActionRead
    from app.schemas.support_case_actions import CaseActionRead

    expected: dict[str, Any]
    if family == "case":
        case = CaseActionRead.model_validate_json(raw)
        root = f"{_API}/cases/{case.case_id}/actions/{case.id}"
        return (
            f"{root}/apply",
            f"{root}/options",
            str(case.id),
            {
                "id": str(case.id),
                "kind": case.kind,
                "authorization_mode": case.authorization_mode,
                "case_revision": case.case_revision,
            },
        )
    if family == "account":
        account = BusinessActionRead.model_validate_json(raw)
        if account.authorization_mode == "single_owner" and stage != "execute":
            raise CLIError("Confirm this owner-authorized action at the execute stage.", CONFLICT)
        root = f"{_API}/cases/{account.case_id}/account-actions/{account.id}/{stage}"
        return (
            root,
            root + "/options",
            str(account.id),
            {
                "id": str(account.id),
                "kind": account.kind,
                "digest": account.digest,
                "authorization_mode": account.authorization_mode,
                "case_revision": account.case_revision,
                "user_revision": account.user_revision,
            },
        )
    if family == "suspend":
        suspension = SuspensionRead.model_validate_json(raw)
        root = f"{_API}/custody/suspensions/{suspension.suspension_id}/{stage}"
        expected = {"target_id": str(suspension.target_id)}
        return root, root + "/options", str(suspension.suspension_id), expected
    if family == "grant":
        grant = GrantChangeRead.model_validate_json(raw)
        root = f"{_API}/custody/grant-changes/{grant.grant_change_id}/{stage}"
        expected = {
            "target_id": str(grant.target_id),
            "capability": grant.capability,
            "enable": grant.enable,
        }
        return root, root + "/options", str(grant.grant_change_id), expected
    registration = RegistrationProposalRead.model_validate_json(raw)
    root = f"{_API}/custody/registrations/{registration.kind}/{registration.proposal_id}/{stage}"
    expected = {"target_id": str(registration.target_id), "kind": registration.kind}
    return root, root + "/options", str(registration.proposal_id), expected


def _decide(args: argparse.Namespace, ctx: Context, *, family: str, stage: str) -> Result:
    _require_private_destination(args.output)
    raw = read_private(args.input)
    path, options_path, action, expected = _decision_plan(family, stage, raw)
    contact_file = getattr(args, "contact_file", None)
    contact = str(UUID(read_private(contact_file).strip())) if contact_file else None
    headers = _session_headers(ctx)
    actor = _profile(ctx, headers)
    plan = _mutation_plan(
        args,
        ctx,
        actor=actor,
        path=path,
        body={
            **expected,
            "contact_ref": contact,
            "receipt_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        },
    )
    if args.dry_run:
        return _preview(args, plan)
    submitted = args.plan.with_name(args.plan.name + ".submitted")
    _require_private_destination(submitted)
    options = ctx.request(
        "POST",
        options_path,
        auth=False,
        headers=headers,
        json={"contact_ref": contact} if contact is not None else {},
    )
    if not isinstance(options, dict):
        raise CLIError("The API did not return a support passkey challenge.", AUTH)
    live = options.get("proposal") if family in {"case", "account"} else options
    if not isinstance(live, dict) or not all(
        live.get(name, "paired" if name == "authorization_mode" else None) == value
        for name, value in expected.items()
    ):
        raise CLIError("The live support proposal no longer matches the private receipt.", CONFLICT)
    if family == "account" and options.get("contact_ref") != contact:
        raise CLIError("The reviewed offline contact reference changed.", CONFLICT)
    proof = _proof_handoff(ctx, headers, str(UUID(options["challenge_id"])))
    if family == "account":
        proof.update(expected_digest=expected["digest"], expected_contact_ref=contact)
    _private_output(submitted, {"plan_sha256": plan["plan_sha256"]})
    reply = ctx.request("POST", path, auth=False, write=True, headers=headers, json=proof)
    from app.api.v1.support import RegistrationDecision
    from app.schemas.support_business_actions import BusinessActionRead
    from app.schemas.support_case_actions import CaseActionRead

    try:
        if family == "case":
            case_decision = CaseActionRead.model_validate(reply)
            if (
                case_decision.applied_at is None
                or reply["id"] != action
                or case_decision.authorization_mode != expected["authorization_mode"]
                or (
                    case_decision.authorization_mode == "single_owner"
                    and case_decision.reviewer_id is not None
                )
            ):
                raise ValueError
        if family == "account":
            readback = BusinessActionRead.model_validate(reply)
            if (
                str(readback.id) != action
                or readback.digest != expected["digest"]
                or readback.authorization_mode != expected["authorization_mode"]
                or ((readback.applied_at is not None) != (stage == "execute"))
            ):
                raise ValueError
        if family == "enrollment":
            registration = RegistrationDecision.model_validate(reply)
            if (registration.invitations is not None) != (stage == "execute"):
                raise ValueError
            if registration.invitations is not None:
                ctx.secrets.update(registration.invitations)
        if family in {"grant", "suspend"} and reply is not None:
            raise ValueError
    except (KeyError, ValueError):
        raise CLIError(
            "The decision response could not be verified.", FAILED, changed=None
        ) from None
    receipt = {"action": action, "stage": stage, "result": reply}
    if family == "enrollment":
        receipt["operator_reference"] = expected["target_id"]
    return _save_receipt(args, receipt)


def _invitation_file(args: argparse.Namespace, ctx: Context) -> Result:
    source = json.loads(read_private(args.input))
    if isinstance(source, list) and args.operator is not None:
        matches = [
            item
            for item in source
            if isinstance(item, dict) and item.get("operator_reference") == str(args.operator)
        ]
        if len(matches) != 1:
            raise CLIError("Select one matching custodian from the private invitation file.")
        operator = matches[0]["operator_reference"]
        invitations = matches[0]["invitations"]
    elif isinstance(source, dict) and source.get("stage") == "execute":
        from app.api.v1.support import RegistrationDecision

        operator = source["operator_reference"]
        if args.operator is not None and str(args.operator) != operator:
            raise CLIError("The enrollment receipt belongs to another operator.")
        invitations = RegistrationDecision.model_validate(source["result"]).invitations
    else:
        raise CLIError(
            "Use a private enrollment execution receipt or select a bootstrap custodian."
        )
    if not isinstance(invitations, (list, tuple)) or not 1 <= len(invitations) <= 2:
        raise CLIError("The receipt has no usable registration invitations.")
    if args.slot > len(invitations):
        raise CLIError("The selected invitation slot is unavailable.")
    invitation = invitations[args.slot - 1]
    if not isinstance(invitation, str) or not _SECRET.fullmatch(invitation):
        raise CLIError("The selected invitation is invalid.")
    ctx.secrets.add(invitation)
    _private_output(
        args.output,
        {
            "version": 1,
            "operator_reference": str(UUID(operator)),
            "invitation": invitation,
        },
    )
    return Result({"written_to_private_file": True})


def _registration_status(ctx: Context, operator: UUID, invitation: str) -> RegistrationStatus:
    from app.api.v1.support import RegistrationStatus

    status = RegistrationStatus.model_validate(
        ctx.request(
            "POST",
            f"{_API}/registration/status",
            auth=False,
            headers={"Origin": ORIGIN},
            json={"invitation": invitation},
        )
    )
    if status.operator_id != operator:
        raise CLIError("The registration invitation belongs to another operator.", AUTH)
    return status


def _register_device(args: argparse.Namespace, ctx: Context) -> Result:
    _require_origin(ctx)
    raw = json.loads(read_private(args.input))
    if not isinstance(raw, dict) or set(raw) != {"version", "operator_reference", "invitation"}:
        raise CLIError("Use a private single-device invitation file.")
    operator = UUID(raw["operator_reference"])
    invitation = raw["invitation"]
    if raw["version"] != 1 or not isinstance(invitation, str) or not _SECRET.fullmatch(invitation):
        raise CLIError("The single-device invitation is invalid.")
    ctx.secrets.add(invitation)
    if not args.apply:
        return Result({"action": "Register a device-bound passkey in Chrome"}, outcome="preview")
    _require_private_destination(args.output)
    status = _registration_status(ctx, operator, invitation)
    if status.state != "pending":
        _private_output(args.output, status.model_dump(mode="json"))
        return Result({"state": status.state, "written_to_private_file": True})
    with _private_terminal() as tty:
        url = ORIGIN + "/#register"
        if not webbrowser.open(url, new=2):
            tty.write(f"Open the device registration page in Chrome: {url}\n")
        tty.write("Select the single-device invitation file in Chrome and register this device.\n")
        tty.write("After Chrome confirms registration, press Enter.\n")
        if not tty.readline():
            raise CLIError("Device registration readback was interrupted.", AUTH, changed=None)
    try:
        status = _registration_status(ctx, operator, invitation)
    except (CLIError, ValueError):
        raise CLIError(
            "Device registration could not be read back.", FAILED, changed=None
        ) from None
    if status.state == "pending":
        raise CLIError("The API has not recorded a passkey for this invitation.", CONFLICT)
    _save_receipt(args, status.model_dump(mode="json"))
    return Result({"state": status.state, "written_to_private_file": True}, changed=True)


def _register_mutations(registry: Registry) -> None:
    for operation in ("propose", "review", "download"):
        leaf = registry.add(
            f"support cases export {operation}",
            lambda a, c, operation=operation: _evidence_command(a, c, operation),
            permission="logs.runtime and logs.export",
            mutates=True,
            preview=True,
            approval=True,
        )
        _mutation_arguments(leaf, case=operation == "propose")
    for operation in ("create", "transition"):
        transition = operation == "transition"
        leaf = registry.add(
            f"support cases {operation}",
            lambda a, c, transition=transition: _change_case(a, c, transition=transition),
            permission="cases.manage",
            mutates=True,
            preview=True,
            approval=True,
        )
        _mutation_arguments(leaf, case=transition)
    def _case_action_schema() -> type[BaseModel]:
        from app.schemas.support_case_actions import CaseActionCreate

        return CaseActionCreate

    def _business_action_schema() -> type[BaseModel]:
        from app.schemas.support_business_actions import BusinessActionCreate

        return BusinessActionCreate

    def _custody_schema(name: str) -> Callable[[], type[BaseModel]]:
        def load() -> type[BaseModel]:
            from app.api.v1 import support as support_api

            return getattr(support_api, name)

        return load

    leaf = registry.add(
        "support cases action propose",
        lambda a, c: _propose(
            a,
            c,
            endpoint=f"/cases/{a.case}/actions",
            schema=_case_action_schema,
            receipt_id="id",
            case_revision=True,
        ),
        permission="cases.manage and case action scope",
        mutates=True,
        preview=True,
        approval=True,
    )
    _mutation_arguments(leaf, case=True)
    leaf = registry.add(
        "support accounts action propose",
        lambda a, c: _propose(
            a,
            c,
            endpoint=f"/cases/{a.case}/account-actions",
            schema=_business_action_schema,
            receipt_id="id",
            business=True,
        ),
        permission="account.request or simulation.start",
        mutates=True,
        preview=True,
        approval=True,
    )
    _mutation_arguments(leaf, case=True)
    for operation, endpoint, schema_name, receipt_id in (
        ("suspend", "/custody/suspensions", "SuspensionRequest", "suspension_id"),
        ("grant", "/custody/grant-changes", "GrantChangeRequest", "grant_change_id"),
        ("enrollment", "/custody/registrations", "RegistrationProposal", "proposal_id"),
    ):
        schema_loader = _custody_schema(schema_name)
        leaf = registry.add(
            f"support custody {operation} propose",
            lambda a, c, endpoint=endpoint, schema=schema_loader, receipt_id=receipt_id: _propose(
                a,
                c,
                endpoint=endpoint,
                schema=schema,
                receipt_id=receipt_id,
            ),
            permission="operator.manage and active custody",
            mutates=True,
            preview=True,
            approval=True,
        )
        _mutation_arguments(leaf)

    for prefix, family, stages in (
        ("support cases action", "case", ("apply",)),
        ("support accounts action", "account", ("review", "execute")),
        ("support custody suspend", "suspend", ("review", "execute")),
        ("support custody grant", "grant", ("review", "execute")),
        ("support custody enrollment", "enrollment", ("review", "execute")),
    ):
        for stage in stages:
            leaf = registry.add(
                f"{prefix} {stage}",
                lambda a, c, family=family, stage=stage: _decide(a, c, family=family, stage=stage),
                permission="existing action authority and fresh passkey",
                mutates=True,
                preview=True,
                approval=True,
            )
            _mutation_arguments(leaf)
            if family == "account" and stage == "review":
                leaf.add_argument("--contact-file", type=Path)


def register(registry: Registry) -> None:
    _register_mutations(registry)
    leaf = registry.add(
        "support custody enrollment invitation",
        _invitation_file,
        permission="private approved enrollment receipt",
        scope="local",
    )
    leaf.add_argument("--input", type=Path, required=True)
    leaf.add_argument("--operator", type=UUID, help="Select a custodian from a bootstrap bundle")
    leaf.add_argument("--slot", type=int, choices=(1, 2), required=True)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support custody enrollment register",
        _register_device,
        permission="one-use registration invitation and device-bound passkey",
        mutates=True,
        preview=True,
        approval=True,
    )
    leaf.add_argument("--input", type=Path, required=True)
    leaf.add_argument("--output", type=Path, required=True)
    leaf.add_argument("--apply", action="store_true")
    leaf = registry.add(
        "support auth login",
        login,
        permission="technical passkey",
        mutates=True,
        preview=True,
        approval=True,
    )
    leaf.add_argument("--operator", type=UUID, required=True)
    leaf.add_argument("--apply", action="store_true")
    leaf = registry.add(
        "support auth logout",
        logout,
        permission="technical session",
        mutates=True,
        preview=True,
    )
    leaf.add_argument("--apply", action="store_true")
    for command, path, permission in (
        ("support auth whoami", "/me", "technical session"),
        ("support health show", "/health", "health.read"),
    ):
        leaf = registry.add(
            command, lambda a, c, path=path: _read(c, path, a.output), permission=permission
        )
        leaf.add_argument("--output", type=Path, required=True)
    for command, suffix, permission in (
        ("show", "", "cases.manage"),
        ("timeline", "/timeline", "cases.manage and logs.runtime"),
    ):
        leaf = registry.add(
            f"support cases {command}",
            lambda a, c, suffix=suffix: _read(c, f"/cases/{a.case}{suffix}", a.output),
            permission=permission,
        )
        leaf.add_argument("--case", type=UUID, required=True)
        leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add("support cases list", _list_cases, permission="cases.manage")
    leaf.add_argument("--limit", type=int, default=25)
    leaf.add_argument("--cursor-from", type=Path)
    leaf.add_argument("--output", type=Path, required=True)
    for source in ("logs", "audit"):
        leaf = registry.add(
            f"support cases {source}",
            lambda a, c, source=source: _read_window(a, c, source),
            permission=f"logs.{'runtime' if source == 'logs' else 'audit'}",
        )
        leaf.add_argument("--case", type=UUID, required=True)
        if source == "logs":
            leaf.add_argument("--request", required=True)
        leaf.add_argument("--hours", type=int, choices=(1, 6, 24), default=1)
        leaf.add_argument("--limit", type=int, default=25)
        leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support cases follow-logs", _follow_logs, permission="logs.runtime and logs.stream"
    )
    leaf.add_argument("--case", type=UUID, required=True)
    leaf.add_argument("--request", required=True)
    leaf.add_argument("--hours", type=int, choices=(1, 6, 24), default=1)
    leaf.add_argument("--seconds", type=int, default=20)
    leaf.add_argument("--max-events", type=int, default=25)
    leaf.add_argument("--cursor-from", type=Path)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support accounts search",
        _search_accounts,
        permission="directory.read",
    )
    leaf.add_argument("--case", type=UUID, required=True)
    leaf.add_argument("--selector-file", type=Path)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support accounts show",
        lambda a, c: _read(c, f"/cases/{a.case}/accounts/{a.account}", a.output),
        permission="directory.read",
    )
    leaf.add_argument("--case", type=UUID, required=True)
    leaf.add_argument("--account", type=UUID, required=True)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support accounts recovery-status",
        lambda a, c: _read(
            c, f"/cases/{a.case}/account-actions/{a.action}/recovery-status", a.output
        ),
        permission="account.request and recovery receipt scope",
    )
    leaf.add_argument("--case", type=UUID, required=True)
    leaf.add_argument("--action", type=UUID, required=True)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support views show",
        lambda a, c: _read(c, f"/views/{a.view}/projection/{a.adapter}", a.output),
        permission="simulation.start and an approved view",
    )
    leaf.add_argument("--view", type=UUID, required=True)
    leaf.add_argument("--adapter", choices=_ADAPTERS, required=True)
    leaf.add_argument("--output", type=Path, required=True)
    leaf = registry.add(
        "support views end",
        _end_view,
        permission="original technical session",
        mutates=True,
        preview=True,
    )
    leaf.add_argument("--view", type=UUID, required=True)
    leaf.add_argument("--apply", action="store_true")

    leaf = registry.add(
        "support overview show",
        _read_overview,
        permission="overview.<domain>.read",
    )
    leaf.add_argument(
        "--domain",
        choices=(
            "company",
            "projects",
            "workforce",
            "inventory",
            "suppliers",
            "documents",
            "finance",
            "approvals",
        ),
        default="company",
    )
    leaf.add_argument("--case", type=UUID)
    leaf.add_argument("--project", type=UUID)
    leaf.add_argument("--output", type=Path, required=True)

    leaf = registry.add(
        "support policy explain",
        lambda a, c: _read(
            c,
            "/policy/explain",
            a.output,
            role_key=a.role,
            permission_key=a.permission,
            case_id=str(a.case) if a.case is not None else None,
        ),
        permission="simulation.start",
    )
    leaf.add_argument("--role", required=True)
    leaf.add_argument("--permission", required=True)
    leaf.add_argument("--case", type=UUID)
    leaf.add_argument("--output", type=Path, required=True)

    leaf = registry.add(
        "support monitor jobs",
        lambda a, c: _read(
            c,
            "/monitor/jobs",
            a.output,
            hours=a.hours,
            limit=a.limit,
            queue=a.queue,
        ),
        permission="jobs.read",
    )
    leaf.add_argument("--hours", type=int, default=24)
    leaf.add_argument("--limit", type=int, default=25)
    leaf.add_argument("--queue", choices=("maintenance", "backup", "email", "reports", "images"))
    leaf.add_argument("--output", type=Path, required=True)

    for command, path, permission in (
        ("support monitor backups", "/monitor/backups", "backups.read"),
        ("support config show", "/config/status", "config.read"),
    ):
        leaf = registry.add(
            command,
            lambda a, c, path=path: _read(c, path, a.output),
            permission=permission,
        )
        leaf.add_argument("--output", type=Path, required=True)

    leaf = registry.add(
        "support incidents show",
        lambda a, c: _read(
            c,
            "/incidents/summary",
            a.output,
            hours=a.hours,
            case_id=str(a.case) if a.case is not None else None,
        ),
        permission="incidents.read",
    )
    leaf.add_argument("--hours", type=int, default=24)
    leaf.add_argument("--case", type=UUID)
    leaf.add_argument("--output", type=Path, required=True)

    for command, path, permission in (
        ("support company context", "/company/context", "technical session"),
        ("support company settings", "/company/settings", "config.read or company.settings.manage"),
        ("support company owner-security", "/company/owner-security", "technical session"),
    ):
        leaf = registry.add(
            command,
            lambda a, c, path=path: _read(c, path, a.output),
            permission=permission,
        )
        leaf.add_argument("--output", type=Path, required=True)

    leaf = registry.add(
        "support company users",
        lambda a, c: _read(
            c,
            "/company/users",
            a.output,
            search=a.search,
            role=a.role,
            state=a.state,
            limit=a.limit,
        ),
        permission="company.directory.read",
    )
    leaf.add_argument("--search")
    leaf.add_argument("--role")
    leaf.add_argument("--state", choices=("active", "inactive", "locked"))
    leaf.add_argument("--limit", type=int, default=25)
    leaf.add_argument("--output", type=Path, required=True)

    for subcmd, suffix, perm in (
        ("user-profile", "", "company.directory.read"),
        ("user-access", "/access", "company.directory.read"),
        ("user-sessions", "/sessions", "company.sessions.read"),
        ("user-activity", "/activity", "company.directory.read"),
    ):
        leaf = registry.add(
            f"support company {subcmd}",
            lambda a, c, suffix=suffix: _read(
                c,
                f"/company/users/{a.user}{suffix}",
                a.output,
                project_id=str(getattr(a, "project", None))
                if getattr(a, "project", None) is not None
                else None,
            ),
            permission=perm,
        )
        leaf.add_argument("--user", type=UUID, required=True)
        if subcmd == "user-access":
            leaf.add_argument("--project", type=UUID)
        leaf.add_argument("--output", type=Path, required=True)

    leaf = registry.add(
        "support company command show",
        lambda a, c: _read(c, f"/company/commands/{a.command}", a.output),
        permission="matching company command capability",
    )
    leaf.add_argument("--command", type=UUID, required=True)
    leaf.add_argument("--output", type=Path, required=True)
