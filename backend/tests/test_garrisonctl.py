import io
import json
from uuid import uuid4

import httpx
import pytest

from scripts import garrisonctl, garrisonctl_auth

ACTOR = "a0300f69-121f-449c-bfa0-7e204feafbad"
USER = "7c764ad1-c6e1-4ad1-a286-84bdd525b7ed"
PROJECT = "954ac3cf-71c2-4492-986e-5f98a5e9343d"
BATCH = "ac033ed0-7643-4e31-9abf-9d647833af01"
TOKEN = "test-only-bearer-do-not-print"


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
        "role": "civil_engineer",
        "updated_at": "2026-11-14T00:00:00Z",
    }
    writes = []

    def handler(request):
        path = request.url.path
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        if path.endswith("/auth/me"):
            return response({"id": ACTOR, "permissions": ["users:manage"]})
        if path.endswith("/users/roles"):
            return response({"items": [{"role": "project_manager", "permissions": []}]})
        if request.method == "GET" and path.endswith("/users"):
            assert request.url.params["email"] == user["email"]
            return response({"items": [user], "total": 1})
        if request.method == "PATCH":
            payload = json.loads(request.content)
            assert payload == {"role": "project_manager", "expected_updated_at": user["updated_at"]}
            writes.append(payload)
            user["role"] = payload["role"]
            return response(user, request_id="role-write")
        return response(user)

    args = ["users", "set-role", "--email", user["email"], "--role", "project_manager"]
    code, preview = invoke([*args, "--dry-run"], handler)
    assert code == 0 and not writes and preview["outcome"] == "preview"
    expect = preview["data"]["plan_sha256"]
    assert invoke([*args, "--apply"], handler)[0] == 2
    assert invoke([*args, "--apply", "--expect", "0" * 64], handler)[0] == 4
    assert not writes
    code, result = invoke([*args, "--apply", "--expect", expect], handler)
    assert code == 0 and len(writes) == 1
    assert result["changed"] is True and result["request_id"] == "role-write"


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
