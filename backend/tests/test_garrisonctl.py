import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl, garrisonctl_auth

ACTOR = "a0300f69-121f-449c-bfa0-7e204feafbad"
USER = "7c764ad1-c6e1-4ad1-a286-84bdd525b7ed"
PROJECT = "954ac3cf-71c2-4492-986e-5f98a5e9343d"
BATCH = "ac033ed0-7643-4e31-9abf-9d647833af01"
TOKEN = "test-only-bearer-do-not-print"
ROLE_MATRIX = json.loads(Path(__file__).with_name("business_role_matrix.json").read_text())
RETIRED_ROLE_KEYS = [*ROLE_MATRIX["retired_roles"], "hr_executive"]
TARGET_ROLE_KEYS = tuple(
    "hr_executive_reader" if role == "hr_executive" else role for role in ROLE_MATRIX["roles"]
)


def invoke(args, handler=None):
    output, diagnostics = io.StringIO(), io.StringIO()
    result = garrisonctl.run(
        [*args, "--json"],
        transport=httpx.MockTransport(handler) if handler else None,
        stdout=output,
        stderr=diagnostics,
    )
    assert not diagnostics.getvalue()
    return result, json.loads(output.getvalue())


@pytest.fixture(autouse=True)
def isolated_cli(monkeypatch):
    monkeypatch.setenv("GARRISON_API_BASE_URL", "https://portal.example.invalid")
    monkeypatch.setenv("GARRISON_ACCESS_TOKEN", TOKEN)
    monkeypatch.delenv("GARRISON_ENVIRONMENT", raising=False)


def response(body, status=200, request_id="api-read"):
    return httpx.Response(status, json=body, headers={"X-Request-ID": request_id})


def test_discover_every_command_and_validate_global_arguments():
    code, envelope = invoke(["capabilities"])
    assert code == 0 and envelope["format_version"] == 1
    entries = {row["command"]: row for row in envelope["data"]["commands"]}
    assert len(entries) >= 42
    assert "config verify" in entries
    assert entries["auth login"]["supports_preview"]
    assert entries["config apply"]["scope"] == "host"
    assert entries["users set-role"]["approval_required"]
    assert entries["finance reconcile"]["mutates"] is False
    for name in entries:
        with pytest.raises(SystemExit) as error:
            garrisonctl.build_parser().parse_args([*name.split(), "--help"])
        assert error.value.code == 0
    code, envelope = invoke(["users", "set-role", "--password", "synthetic-unrecognized"])
    assert code == 2 and "synthetic-unrecognized" not in json.dumps(envelope)
    code, envelope = invoke(["--base-url", "http://portal.example.invalid", "health", "check"])
    assert code == 2 and envelope["changed"] is False


def test_otp_session_refresh_logout_and_output_are_private(tmp_path, monkeypatch):
    monkeypatch.delenv("GARRISON_ACCESS_TOKEN")
    tmp_path.chmod(0o700)
    path = tmp_path / "session.json"
    args = ["--session-file", str(path)]
    password, otp = "Synthetic-password", "876543"
    secrets = iter((password, otp))
    monkeypatch.setattr(garrisonctl_auth, "prompt_secret", lambda _: next(secrets))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            assert json.loads(request.content)["password"] == password
            return response({"challenge_id": "challenge", "dev_otp": otp})
        if request.url.path.endswith("/verify-otp"):
            assert json.loads(request.content)["otp"] == otp
            return httpx.Response(
                200,
                json={"access_token": TOKEN, "expires_in_seconds": 1, "user": {"id": ACTOR}},
                headers={"Set-Cookie": "refresh_token=refresh-one; Path=/api/v1/auth; Secure"},
            )
        if request.url.path.endswith("/refresh"):
            assert request.headers["Cookie"] == "refresh_token=refresh-one"
            return httpx.Response(
                200,
                json={
                    "access_token": "rotated-bearer",
                    "expires_in_seconds": 300,
                    "user": {"id": ACTOR},
                },
                headers={"Set-Cookie": "refresh_token=refresh-two; Path=/api/v1/auth; Secure"},
            )
        if request.url.path.endswith("/me"):
            assert request.headers["Authorization"] == "Bearer rotated-bearer"
            return response({"id": ACTOR})
        assert request.url.path.endswith("/logout")
        assert request.headers["Cookie"] == "refresh_token=refresh-two"
        return response({"message": "Signed out."})

    code, preview = invoke(
        [*args, "auth", "login", "--email", "admin@example.com", "--dry-run"], handler
    )
    assert code == 0 and not path.exists() and not calls and preview["changed"] is False
    code, session = invoke([*args, "auth", "login", "--email", "admin@example.com"], handler)
    assert code == 0 and session["data"] == {"id": ACTOR} and path.stat().st_mode & 0o777 == 0o600
    assert all(value not in json.dumps(session) for value in (password, otp, TOKEN, "refresh-one"))
    code, session = invoke([*args, "auth", "whoami"], handler)
    assert code == 0 and session["data"]["id"] == ACTOR
    code, session = invoke([*args, "auth", "logout"], handler)
    assert code == 0 and session["data"]["signed_out"] and not path.exists()


def test_token_file_access_errors_and_secret_redaction(tmp_path, monkeypatch):
    monkeypatch.delenv("GARRISON_ACCESS_TOKEN")
    path = tmp_path / "token"
    path.write_text(TOKEN)
    path.chmod(0o644)
    assert invoke(["auth", "whoami", "--token-file", str(path)])[0] != 0
    path.chmod(0o600)
    link = tmp_path / "linked"
    link.symlink_to(path)
    assert invoke(["auth", "whoami", "--token-file", str(link)])[0] != 0

    def handler(request):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        return response({"detail": TOKEN, "errors": [{"msg": TOKEN}]}, 403)

    code, result = invoke(["auth", "whoami", "--token-file", str(path)], handler)
    assert code == 3 and TOKEN not in json.dumps(result)
    assert result["request_id"] == "api-read"


def test_role_plan_requires_matching_state_and_verifies_apply():
    user = {
        "id": USER,
        "email": "engineer@example.com",
        "role": "quantity_surveyor",
        "updated_at": "2026-11-14T00:00:00Z",
    }
    writes = []

    def handler(request):
        path = request.url.path
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if path.endswith("/auth/me"):
            return response({"id": ACTOR, "permissions": ["users:manage"]})
        if path.endswith("/users/roles"):
            return response(
                {
                    "items": [
                        {
                            "role": "group_project_manager",
                            "permissions": [],
                            "assignable": True,
                        }
                    ]
                }
            )
        if request.method == "GET" and path.endswith("/users"):
            assert request.url.params["email"] == user["email"]
            return response({"items": [user], "total": 1})
        if request.method == "PATCH":
            payload = json.loads(request.content)
            assert payload == {
                "role": "group_project_manager",
                "expected_updated_at": user["updated_at"],
            }
            writes.append(payload)
            user["role"] = payload["role"]
            return response(user, request_id="role-write")
        return response(user)

    args = ["users", "set-role", "--email", user["email"], "--role", "group_project_manager"]
    code, preview = invoke([*args, "--dry-run"], handler)
    assert code == 0, preview["errors"]
    assert not writes and preview["outcome"] == "preview"
    expect = preview["data"]["plan_sha256"]
    assert invoke([*args, "--apply"], handler)[0] == 2
    assert invoke([*args, "--apply", "--expect", "0" * 64], handler)[0] == 4
    assert not writes
    code, result = invoke([*args, "--apply", "--expect", expect], handler)
    assert code == 0 and len(writes) == 1
    assert result["changed"] is True and result["request_id"] == "role-write"


@pytest.mark.parametrize("retired_role", RETIRED_ROLE_KEYS)
def test_role_command_rejects_each_retired_key_before_planning_or_writing(retired_role: str):
    target = {
        "id": USER,
        "email": "target@example.com",
        "role": "quantity_surveyor",
        "updated_at": "2026-11-14T00:00:00Z",
    }
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth/me"):
            return response({"id": ACTOR, "permissions": ["users:manage"]})
        if request.url.path == "/api/v1/users":
            return response({"items": [target], "total": 1})
        if request.url.path == f"/api/v1/users/{USER}":
            return response(target)
        if request.url.path == "/api/v1/users/roles":
            return response(
                {
                    "items": [
                        {"role": role, "permissions": [], "assignable": True}
                        for role in TARGET_ROLE_KEYS
                    ]
                }
            )
        raise AssertionError(f"Unexpected CLI request: {request.method} {request.url.path}")

    code, result = invoke(
        [
            "users",
            "set-role",
            "--email",
            target["email"],
            "--role",
            retired_role,
            "--dry-run",
        ],
        handler,
    )

    assert code != 0
    assert "Unknown role" in json.dumps(result)
    assert not any(method in {"POST", "PATCH", "DELETE"} for method, _ in calls)


def test_import_retry_keeps_key_and_partial_receipt_fails(tmp_path):
    path = tmp_path / "stock.csv"
    path.write_text("item_code,location_code,quantity,notes\nA,B,1,\n")
    keys = []
    state = {
        "batch_id": BATCH,
        "template_type": "opening_stock",
        "status": "completed",
        "row_count": 1,
        "error_count": 0,
        "summary": {"created": 1, "skipped": 0},
    }

    def handler(request):
        if request.url.path.endswith("/auth/me"):
            return response({"id": ACTOR, "permissions": ["users:manage"]})
        if request.url.path.endswith("/preview"):
            return response({"valid": True, "row_count": 1})
        if request.url.path.endswith("/run"):
            keys.append(request.headers["Idempotency-Key"])
        return response(state)

    args = [
        "imports",
        "run",
        "--type",
        "opening_stock",
        "--file",
        str(path),
        "--operation-id",
        str(uuid4()),
    ]
    code, preview = invoke([*args, "--dry-run"], handler)
    assert code == 0 and not keys
    apply = [*args, "--apply", "--expect", preview["data"]["plan_sha256"]]
    assert invoke(apply, handler)[0] == 0
    assert invoke(apply, handler)[0] == 0
    assert keys == [preview["data"]["idempotency_key"]] * 2
    state["summary"] = {"created": 0, "skipped": 1, "errors": [{"message": "private"}]}
    code, partial = invoke(apply, handler)
    assert code == 6 and partial["data"]["skipped"] == 1
    assert "private" not in json.dumps(partial)


def test_reconciliation_exact_amounts_and_no_unrelated_fields(tmp_path):
    path = tmp_path / "expected.json"
    path.write_text(
        json.dumps(
            {
                "invoices": {USER: {"amount": "99.00", "tax_amount": "1.00"}},
                "invoice_totals": {"amount": "99.00"},
            }
        )
    )

    def handler(request):
        assert request.method == "GET" and request.url.params["project_id"] == PROJECT
        return response(
            {
                "total": 1,
                "items": [
                    {"id": USER, "amount": "99", "tax_amount": "2.00", "notes": "confidential"},
                ],
            }
        )

    args = ["finance", "reconcile", "--project-id", PROJECT, "--expected-file", str(path)]
    code, result = invoke(args, handler)
    assert code == 7 and result["changed"] is False
    assert result["data"]["invoices"]["mismatched"][0]["fields"] == [
        {"field": "tax_amount", "expected": "1.00", "actual": "2.00"},
    ]
    assert result["data"]["invoice_totals"]["matched"] == ["total"]
    assert "confidential" not in json.dumps(result)


def test_health_checks_payload_and_errors_do_not_echo_body():
    code, result = invoke(
        ["health", "check"],
        lambda _: response(
            {"status": "ready", "database": "connected", "secret": TOKEN},
        ),
    )
    assert code == 0 and result["data"] == {"status": "ready", "database": "connected"}
    code, result = invoke(["health", "check"], lambda _: response({"status": "not_ready"}))
    assert code == 5 and result["changed"] is False


def test_technical_cli_login_and_private_readback_never_send_business_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import garrisonctl_support

    tmp_path.chmod(0o700)
    session = tmp_path / "technical-session.json"
    output = tmp_path / "profile.json"
    secret, csrf, code = "A" * 43, "B" * 43, "123456789abc"
    handoff = str(uuid4())
    tokens = iter([secret, csrf])
    monkeypatch.setattr(garrisonctl_support, "token_urlsafe", lambda _: next(tokens))
    monkeypatch.setattr(garrisonctl_support, "token_hex", lambda _: code)
    monkeypatch.setattr(garrisonctl_support, "_private_terminal", lambda: io.StringIO("\n" * 300))
    monkeypatch.setattr(
        garrisonctl_support.webbrowser, "open",
        lambda url, **_: url == f"https://superadmin.garrisons.lk/#cli={handoff}",
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.url.host == "superadmin.garrisons.lk"
        assert "Authorization" not in request.headers
        if request.url.path.endswith("/start"):
            body = json.loads(request.content)
            assert body["operator_id"] == ACTOR
            assert not any(x in request.content.decode() for x in (secret, csrf, code))
            return response({"challenge_id": handoff})
        assert request.headers["X-Support-CSRF"] == csrf
        assert f"__Host-garrison-support={secret}" in request.headers["Cookie"]
        if request.url.path.endswith("/logout"):
            return httpx.Response(204)
        if request.url.path.endswith("/health"):
            return response({"detail": "restricted"}, status=403)
        return response({"operator_id": ACTOR, "capabilities": ["cases.manage"]})

    settings = ["--session-file", str(session)]
    login = ["support", "auth", "login", "--operator", ACTOR, *settings]
    result, preview = invoke(login, handler)
    assert result == 0 and preview["outcome"] == "preview" and not seen
    result, connected = invoke([*login, "--apply"], handler)
    assert result == 0 and connected["data"]["authenticated"]
    assert session.stat().st_mode & 0o777 == 0o600
    result, profile = invoke(
        ["support", "auth", "whoami", "--output", str(output), *settings], handler
    )
    assert result == 0 and profile["data"] == {"written_to_private_file": True}
    assert json.loads(output.read_text())["operator_id"] == ACTOR
    assert output.stat().st_mode & 0o777 == 0o600
    denied = tmp_path / "denied.json"
    result, failure = invoke(
        ["support", "health", "show", "--output", str(denied), *settings], handler
    )
    assert result != 0 and failure["errors"][0]["details"]["http_status"] == 403
    assert not denied.exists()
    result, signout = invoke(["support", "auth", "logout", "--apply", *settings], handler)
    assert result == 0 and not session.exists()
    for value in (secret, csrf, code, TOKEN):
        assert value not in json.dumps([preview, connected, profile, failure, signout])
    result, rejected = invoke(
        ["--base-url", "https://portal.example.invalid", *login, "--apply"], handler
    )
    assert result != 0 and rejected["outcome"] == "error"
    assert len(seen) == 5


def _support_file(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload))
    path.chmod(0o600)
    return str(path)


def _technical_session(tmp_path: Path) -> list[str]:
    tmp_path.chmod(0o700)
    return ["--session-file", _support_file(tmp_path / "support.json", {
        "origin": "https://superadmin.garrisons.lk",
        "support_token": "Z" * 43,
        "support_csrf": "X" * 43,
    })]


def test_support_account_lookup_uses_case_scope_and_writes_private_result(tmp_path: Path) -> None:
    flags = _technical_session(tmp_path)
    output = tmp_path / "account.json"
    payload = {"case_id": PROJECT, "user_id": ACTOR, "email_masked": "a***@example.com"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.host == "superadmin.garrisons.lk"
        assert request.url.path == f"/api/v1/support/cases/{PROJECT}/accounts"
        assert not request.url.query and "Authorization" not in request.headers
        assert "__Host-garrison-support=" + "Z" * 43 in request.headers["Cookie"]
        return response(payload)

    args = ["support", "accounts", "search", "--case", PROJECT, "--output", str(output), *flags]
    status, result = invoke(args, handler)
    assert status == 0 and result["data"] == {"written_to_private_file": True}
    assert json.loads(output.read_text()) == payload
    assert output.stat().st_mode & 0o777 == 0o600


def test_support_account_selector_is_sent_only_in_private_request_body(tmp_path: Path) -> None:
    flags = _technical_session(tmp_path)
    output = tmp_path / "matched.json"
    selector = {"field": "email", "value": "synthetic-operator-search@example.com"}
    fixture = _support_file(tmp_path / "selector.json", selector)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/api/v1/support/cases/{PROJECT}/accounts/search"
        assert not request.url.query and "Authorization" not in request.headers
        assert json.loads(request.content) == selector
        return response({"case_id": PROJECT, "user_id": ACTOR})

    status, result = invoke([
        "support", "accounts", "search", "--case", PROJECT, "--selector-file", fixture,
        "--output", str(output), *flags,
    ], handler)
    assert status == 0 and result["data"] == {"written_to_private_file": True}
    assert selector["value"] not in json.dumps(result) + output.read_text()


def test_support_cli_follows_case_evidence_and_resumes_from_private_cursor(tmp_path: Path) -> None:
    flags = _technical_session(tmp_path)
    output = tmp_path / "stream.json"
    source = uuid4().hex
    cursor = str(uuid4())
    receipt = _support_file(tmp_path / "previous.json", {
        "case_id": PROJECT, "request_id": source, "last_event_id": cursor,
    })
    item = {
        "id": str(uuid4()), "occurred_at": "2026-11-17T01:00:00Z",
        "kind": "request", "method": "GET", "status_code": 200,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "superadmin.garrisons.lk"
        assert request.url.path == f"/api/v1/support/cases/{PROJECT}/logs/stream"
        assert request.url.params["request_id"] == source
        assert request.headers["Last-Event-ID"] == cursor
        assert "Authorization" not in request.headers
        assert "__Host-garrison-support=" + "Z" * 43 in request.headers["Cookie"]
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, text=(
            ": keep-alive\n\n"
            f"id: {item['id']}\ndata: {json.dumps({**item, 'private': 'synthetic-marker'})}\n\n"
            'event: closed\ndata: {"reason": "access_ended"}\n\n'
        ))

    args = ["support", "cases", "follow-logs", "--case", PROJECT, "--request", source,
            "--output", str(output), "--cursor-from", receipt, *flags]
    status, result = invoke(args, handler)
    assert status == 0 and result["data"]["finished_by"] == "access_ended"
    contents = json.loads(output.read_text())
    assert contents["items"] == [item] and contents["last_event_id"] == item["id"]
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("corrupt", [False, True])
def test_support_cli_download_verifies_approved_bytes_before_private_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, corrupt: bool,
) -> None:
    from scripts import garrisonctl_support

    flags = _technical_session(tmp_path)
    export_id, challenge = str(uuid4()), str(uuid4())
    source = uuid4().hex
    content = b"record_type,event_id\nmanifest,\n"
    digest = hashlib.sha256(content).hexdigest()
    approval = {
        "id": export_id, "case_id": PROJECT, "filters": {
            "request_id": source, "started_at": "2026-11-17T00:00:00Z",
            "ended_at": "2026-11-17T01:00:00Z", "limit": 10_000, "status_code": None,
        },
        "reason": "incident_review", "row_count": 0, "truncated": False, "sha256": digest,
        "expires_at": "2026-11-17T01:15:00Z",
        "approved_at": "2026-11-17T01:01:00Z", "downloaded_at": None,
    }
    receipt = _support_file(tmp_path / "approval.json", approval)
    plan = tmp_path / "plan.json"
    output = tmp_path / "evidence.csv"
    attempts: list[str] = []

    def handoff(_ctx, headers, proof_id):
        assert proof_id == challenge and "Authorization" not in headers
        return {"challenge_id": proof_id, "credential": {"id": "fixture"}}

    monkeypatch.setattr(garrisonctl_support, "_proof_handoff", handoff)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "superadmin.garrisons.lk"
        assert "Authorization" not in request.headers
        if request.url.path.endswith("/me"):
            return response({"operator_id": ACTOR})
        path = f"/api/v1/support/cases/{PROJECT}/exports/{export_id}/download"
        attempts.append(request.url.path)
        if request.url.path == path + "/options":
            return response({"challenge_id": challenge, "export": approval})
        assert request.url.path == path
        assert json.loads(request.content)["expected_sha256"] == digest
        return httpx.Response(200, content=content + (b"wrong" if corrupt else b""), headers={
            "Content-Type": "text/csv", "X-Support-Export-Sha256": digest,
        })

    command = ["support", "cases", "export", "download", "--input", receipt, *flags]
    code, preview = invoke([*command, "--dry-run", "--output", str(plan)], handler)
    assert code == 0 and not attempts
    code, result = invoke([
        *command, "--apply", "--expect", preview["data"]["plan_sha256"],
        "--plan", str(plan), "--output", str(output),
    ], handler)
    assert len(attempts) == 2
    if corrupt:
        assert code != 0 and not output.exists()
        assert result["changed"] is True
        return
    assert code == 0
    assert result["data"]["sha256"] == digest and output.read_bytes() == content
    assert output.stat().st_mode & 0o777 == 0o600


def test_support_case_transition_declines_stale_plan_and_verifies_exact_record(
    tmp_path: Path,
) -> None:
    flags = _technical_session(tmp_path)
    payload = {"status": "investigating", "reason_code": "functional"}
    args = ["support", "cases", "transition", "--case", PROJECT, *flags,
            "--input", _support_file(tmp_path / "input.json", payload)]
    current = {"id": PROJECT, "owner_id": ACTOR, "external_ref": "private-synthetic-reference",
               "status": "open", "revision": 1, "severity": "high", "reason_code": "functional",
               "created_at": "2026-11-01T00:00:00Z", "updated_at": "2026-11-01T00:00:00Z"}
    attempts = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "superadmin.garrisons.lk"
        assert "Authorization" not in req.headers
        if req.url.path.endswith("/me"):
            return response({"operator_id": ACTOR})
        if req.method == "POST":
            assert req.url.path.endswith(f"/cases/{PROJECT}/transitions")
            assert req.headers["If-Match"] == '"1"'
            assert req.headers["X-Support-CSRF"] == "X" * 43
            attempts.append(json.loads(req.content))
            current.update(revision=2, status="investigating")
        return response(current)

    plan, receipt = tmp_path / "plan.json", tmp_path / "receipt.json"
    code, preview = invoke([*args, "--dry-run", "--output", str(plan)], handler)
    assert code == 0 and not attempts
    apply = [*args, "--apply", "--output", str(receipt), "--plan", str(plan),
             "--expect", preview["data"]["plan_sha256"]]
    current["revision"] = 2
    assert invoke(apply, handler)[0] != 0
    assert not attempts and not receipt.exists()
    current["revision"] = 1
    code, verified = invoke(apply, handler)
    assert code == 0 and verified["changed"] is True and attempts == [payload]
    assert json.loads(receipt.read_text())["revision"] == 2
    assert "private-synthetic-reference" not in json.dumps(verified)


def test_support_account_proposal_retries_same_intent_with_existing_api_key(tmp_path: Path) -> None:
    flags = _technical_session(tmp_path)
    body = {"kind": "unlock", "user_id": USER, "user_revision": 4, "case_revision": 8,
            "reason_code": "failed_sign_in", "reason": "Private synthetic justification"}
    cmd = ["support", "accounts", "action", "propose", "--case", PROJECT, *flags,
           "--input", _support_file(tmp_path / "input.json", body)]
    keys: list[str] = []
    receipts: dict[str, str] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/me"):
            return response({"operator_id": ACTOR})
        assert req.url.path.endswith(f"/cases/{PROJECT}/account-actions")
        assert req.method == "POST"
        key = req.headers["Idempotency-Key"]
        keys.append(key)
        return response({
            **json.loads(req.content), "id": receipts.setdefault(key, str(uuid4())),
            "case_id": PROJECT, "digest": "b" * 64, "expires_at": "2026-11-17T00:15:00Z",
            "applied_at": None,
        }, status=201)

    for index in range(2):
        plan = tmp_path / f"plan-{index}.json"
        code, preview = invoke([*cmd, "--dry-run", "--output", str(plan)], handler)
        assert code == 0
        for retry in range(2):
            receipt = tmp_path / f"receipt-{index}-{retry}.json"
            code, approved = invoke([
                *cmd, "--apply", "--plan", str(plan), "--expect", preview["data"]["plan_sha256"],
                "--output", str(receipt),
            ], handler)
            assert code == 0 and "Private synthetic justification" not in json.dumps(approved)
            assert "Private synthetic justification" in receipt.read_text()
    assert keys[0] == keys[1] and keys[2] == keys[3] and keys[0] != keys[2]


def test_support_custody_proposal_records_attempt_before_unkeyed_write(tmp_path: Path) -> None:
    flags = _technical_session(tmp_path)
    cmd = ["support", "custody", "grant", "propose", *flags, "--input",
           _support_file(tmp_path / "input.json", {
               "target_id": USER, "capability": "health.read", "enable": True,
           })]
    attempts = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/me"):
            return response({"operator_id": ACTOR})
        assert req.url.path.endswith("/custody/grant-changes")
        attempts.append(req)
        raise httpx.ConnectError("synthetic uncertain receipt")

    plan = tmp_path / "plan.json"
    code, preview = invoke([*cmd, "--dry-run", "--output", str(plan)], handler)
    assert code == 0
    for retry in range(2):
        code, _ = invoke([*cmd, "--apply", "--plan", str(plan), "--expect",
                          preview["data"]["plan_sha256"], "--output",
                          str(tmp_path / f"receipt-{retry}.json")], handler)
        assert code != 0
    assert len(attempts) == 1
    assert (tmp_path / "plan.json.submitted").stat().st_mode & 0o777 == 0o600


def test_cli_review_uses_original_action_route_and_rejects_invalid_seal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from base64 import urlsafe_b64decode, urlsafe_b64encode

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    from scripts import garrisonctl_support

    flags = _technical_session(tmp_path)
    reference, challenge, action = (str(uuid4()) for _ in range(3))
    receipt = {"suspension_id": action, "target_id": USER, "expires_at": "2026-11-17T00:00:00Z"}
    command = ["support", "custody", "suspend", "review", *flags, "--input",
               _support_file(tmp_path / "proposal.json", receipt)]
    path = f"/api/v1/support/custody/suspensions/{action}/review"
    assertion = {
        "challenge_id": challenge,
        "credential": {
            "id": "opaque", "rawId": "opaque", "type": "public-key",
            "response": {
                "authenticatorData": "opaque", "clientDataJSON": "opaque",
                "signature": "opaque", "userHandle": "opaque",
            },
        },
    }
    monkeypatch.setattr(garrisonctl_support, "_private_terminal", lambda: io.StringIO("\n" * 500))
    monkeypatch.setattr(garrisonctl_support.webbrowser, "open", lambda *_, **__: True)
    sealed = ""
    corrupt = True
    decisions: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal sealed
        assert "Authorization" not in req.headers
        if req.url.path.endswith("/me"):
            return response({"operator_id": ACTOR})
        assert req.headers["X-Support-CSRF"] == "X" * 43
        if req.url.path == f"{path}/options":
            return response({"target_id": USER, "challenge_id": challenge})
        if req.url.path.endswith("/start"):
            value = json.loads(req.content)["encryption_key"]
            der = urlsafe_b64decode(value + "=" * (-len(value) % 4))
            pub = serialization.load_der_public_key(der)
            assert isinstance(pub, rsa.RSAPublicKey)
            oaep = padding.OAEP(
                mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None,
            )
            key = AESGCM.generate_key(bit_length=256)
            nonce = bytes(range(12))
            data = AESGCM(key).encrypt(
                nonce, json.dumps(assertion).encode(),
                (str(uuid4()) if corrupt else reference).encode(),
            )
            sealed = urlsafe_b64encode(pub.encrypt(key, oaep) + nonce + data).decode().rstrip("=")
            return response({"reference": reference})
        if req.url.path.endswith("/take"):
            assert json.loads(req.content) == {"reference": reference}
            return response({"sealed": sealed})
        assert req.url.path == path
        decisions.append(json.loads(req.content))
        return httpx.Response(204)

    plan = tmp_path / "plan.json"
    code, preview = invoke([*command, "--dry-run", "--output", str(plan)], handler)
    assert code == 0
    args = [*command, "--apply", "--plan", str(plan), "--expect", preview["data"]["plan_sha256"]]
    bad = tmp_path / "bad.json"
    code, denied = invoke([*args, "--output", str(bad)], handler)
    assert code != 0 and not bad.exists() and not decisions
    assert sealed not in json.dumps(denied)
    corrupt = False
    result = tmp_path / "decision.json"
    code, applied = invoke([*args, "--output", str(result)], handler)
    assert code == 0 and applied["changed"] is True
    assert decisions == [assertion]
    assert json.loads(result.read_text()) == {"action": action, "stage": "review", "result": None}


def test_cli_device_registration_splits_invitations_and_confirms_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import garrisonctl_support

    tmp_path.chmod(0o700)
    first, second = "B" * 43, "C" * 43
    custody = _support_file(tmp_path / "execution.json", {
        "action": PROJECT, "stage": "execute", "operator_reference": ACTOR,
        "result": {"invitations": [first, second]},
    })
    single = tmp_path / "single-device.json"
    receipt = tmp_path / "registration.json"
    code, split = invoke([
        "support", "custody", "enrollment", "invitation", "--input", custody,
        "--slot", "2", "--output", str(single),
    ])
    assert code == 0
    assert single.stat().st_mode & 0o777 == 0o600
    assert json.loads(single.read_text()) == {
        "version": 1, "operator_reference": ACTOR, "invitation": second,
    }
    url: list[str] = []
    monkeypatch.setattr(garrisonctl_support, "_private_terminal", lambda: io.StringIO("\n" * 400))

    def open_browser(target: str, **_: object) -> bool:
        url.append(target)
        return True

    monkeypatch.setattr(garrisonctl_support.webbrowser, "open", open_browser)
    requests = 0
    status = iter(["pending", "registered"])

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        assert req.url.host == "superadmin.garrisons.lk"
        assert req.url.path == "/api/v1/support/registration/status"
        assert "Cookie" not in req.headers and "Authorization" not in req.headers
        assert json.loads(req.content) == {"invitation": second}
        return response({"operator_id": ACTOR, "state": next(status)})

    args = ["support", "custody", "enrollment", "register",
            "--input", str(single), "--output", str(receipt)]
    code, preview = invoke(args, handler)
    assert code == 0 and preview["outcome"] == "preview" and not requests
    code, registered = invoke([*args, "--apply"], handler)
    assert code == 0 and registered["changed"] and registered["data"]["state"] == "registered"
    assert requests == 2 and url == ["https://superadmin.garrisons.lk/#register"]
    assert json.loads(receipt.read_text()) == {"operator_id": ACTOR, "state": "registered"}
    assert all(value not in json.dumps([split, preview, registered]) for value in (first, second))
