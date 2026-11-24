from collections.abc import AsyncIterator
from datetime import date, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr
from sqlalchemy import delete, select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.support import CSRF_COOKIE
from app.config import Settings
from app.database import AsyncSessionLocal
from app.models.auth import AuthRefreshToken, AuthSession
from app.models.hr import HrDepartment, HrEmployee, HrPosition
from app.models.import_batch import ImportBatch
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.support_admin_commands import (
    SupportAdminCommand,
    SupportAdminCommandEvent,
)
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_identity import SupportOperator
from app.models.support_oversight import COMPANY_CONTROL_CAPABILITIES
from app.models.support_registration import SupportBootstrap
from app.models.task_outbox import TaskOutbox
from app.models.user import User
from app.services.email_service import EmailDeliveryError
from app.services.import_service import (
    encrypt_import_payload_with_key_id,
    import_outbox_dedupe_key,
)
from app.utils.permissions import (
    ROLE_GROUP_PROJECT_MANAGER,
    ROLE_HR_EXECUTIVE,
    ROLE_MANAGING_DIRECTOR,
    ROLE_MEP_PROJECT_MANAGER,
    ROLE_QUANTITY_SURVEYOR,
    ROLE_SITE_SUPERVISOR,
)
from app.utils.security import create_access_token, utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client, seed_operator, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.fixture(autouse=True)
async def cleanup_support_bootstrap() -> AsyncIterator[None]:
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(SupportBootstrap))
        await db.commit()


async def grant_capabilities(operator_id: UUID, *capabilities: str) -> None:
    async with AsyncSessionLocal() as session:
        for cap in capabilities:
            existing = await session.get(SupportOperatorGrant, (operator_id, cap))
            if existing is None:
                session.add(SupportOperatorGrant(operator_id=operator_id, capability=cap))
        await session.commit()


async def execute_planned_command(
    browser: httpx.AsyncClient,
    operator_identity: tuple[UUID, bytes, ec.EllipticCurvePrivateKey],
    planned: dict,
    *,
    counter: int,
) -> httpx.Response:
    command_id = planned["command_id"]
    opts_resp = await browser.post(f"{API}/company/commands/{command_id}/proof/options")
    assert opts_resp.status_code == 200, opts_resp.text
    proof_payload = {
        **sign(opts_resp.json(), *operator_identity, counter=counter),
        "expected_plan_sha256": planned["plan_sha256"],
    }
    return await browser.post(
        f"{API}/company/commands/{command_id}/execute", json=proof_payload
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_email_only_assurance_invalidation_and_passkey_step_up_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify F-01/V-18/V-19: flag-off invalidates pending challenges and low-assurance sessions."""
    await skip_if_database_unavailable()
    operator, _, _ = await seed_operator()
    mailbox = "owner-assurance@garrisons.lk"
    state = {"otp_only": True}
    codes: list[str] = []

    def current_settings() -> Settings:
        return Settings(
            app_env="test",
            support_portal_enabled=True,
            support_custody_mode="single_owner",
            support_email_otp_only_login=state["otp_only"],
            support_email_otp_key=SecretStr("assurance-test-support-email-otp-key-32b"),
            support_email_otp_recipients={operator: mailbox},
        )

    def fake_send(_sender: object, *, recipients: list[str], subject: str, body: str) -> int:
        assert recipients == [mailbox] and "Super Admin" in subject
        codes.append(body.splitlines()[0].rsplit(" ", 1)[-1])
        return 1

    monkeypatch.setattr("app.api.v1.support.get_settings", current_settings)
    monkeypatch.setattr("app.services.support_identity.get_settings", current_settings)
    monkeypatch.setattr("app.services.support_identity.EmailService.send", fake_send)

    async with AsyncSessionLocal() as db:
        await db.execute(delete(SupportBootstrap))
        db.add(
            SupportBootstrap(
                id=1,
                first_id=operator,
                custody_mode="single_owner",
                approval_digest="c" * 64,
                started_at=utc_now(),
                activated_at=utc_now(),
            )
        )
        await db.commit()

    await grant_capabilities(operator, "cases.manage", "logs.audit")

    async with client() as browser:
        # 1. V-18: Issue email-only challenge, then turn flag off before consuming OTP -> denied!
        req1 = await browser.post(f"{API}/auth/request-otp", json={"operator_id": str(operator)})
        assert req1.status_code == 200
        ref1 = req1.json()["otp_reference"]
        code1 = codes.pop()

        state["otp_only"] = False
        denied_consume = await browser.post(
            f"{API}/auth/verify-otp", json={"otp_reference": ref1, "otp": code1}
        )
        assert denied_consume.status_code == 401
        assert "set-cookie" not in denied_consume.headers

        # 2. Re-enable flag, complete login -> low-assurance session is active for basic read,
        # but denied on high-risk direct case mutation and case audit read (V-19).
        state["otp_only"] = True
        req2 = await browser.post(f"{API}/auth/request-otp", json={"operator_id": str(operator)})
        assert req2.status_code == 200
        code2 = codes.pop()
        verified = await browser.post(
            f"{API}/auth/verify-otp",
            json={"otp_reference": req2.json()["otp_reference"], "otp": code2},
        )
        assert verified.status_code == 200
        browser.headers["x-support-csrf"] = browser.cookies[CSRF_COOKIE]

        sec = await browser.get(f"{API}/company/owner-security")
        assert sec.status_code == 200
        assert sec.json()["session_auth_method"] == "email_otp_only"

        # High-risk direct case mutation without passkey session assurance is rejected with 403.
        create_case = await browser.post(
            f"{API}/cases",
            json={
                "external_ref": f"inc-{uuid4().hex[:8]}",
                "severity": "medium",
                "reason_code": "access",
            },
        )
        assert create_case.status_code == 403
        assert create_case.json()["error_code"] == "SUPPORT_PASSKEY_ASSURANCE_REQUIRED"

        # 3. Disabling support_email_otp_only_login immediately invalidates low-assurance sessions.
        state["otp_only"] = False
        assert (await browser.get(f"{API}/me")).status_code == 401


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_single_owner_permission_view_projection_without_second_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify C-45/T-22/G74: single owner proposes, executes, and reads permission view solo."""
    await skip_if_database_unavailable()
    settings = Settings(
        app_env="test",
        support_portal_enabled=True,
        support_custody_mode="single_owner",
    )
    monkeypatch.setattr("app.services.support_identity.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.support_business_actions.get_settings", lambda: settings)

    async with client() as owner_client:
        owner = await login(owner_client, custodian=False)
        case_id, subject_id = uuid4(), uuid4()
        async with AsyncSessionLocal() as db:
            await db.execute(delete(SupportBootstrap))
            db.add(
                SupportBootstrap(
                    id=1,
                    first_id=owner[0],
                    custody_mode="single_owner",
                    approval_digest="a" * 64,
                    started_at=utc_now(),
                    activated_at=utc_now(),
                )
            )
            db.add(
                User(
                    id=subject_id,
                    full_name="Solo View Subject",
                    email=f"solo-{subject_id.hex[:8]}@example.test",
                    role=ROLE_HR_EXECUTIVE,
                    is_active=True,
                )
            )
            db.add(
                SupportCase(
                    id=case_id,
                    owner_id=owner[0],
                    external_ref=f"solo-view-{case_id.hex[:8]}",
                    reason_code="access",
                    status="open",
                    severity="low",
                )
            )
            await db.flush()
            from app.models.support_directory import SupportCaseSubject

            db.add(SupportCaseSubject(case_id=case_id, user_id=subject_id))
            db.add(SupportCaseMember(case_id=case_id, operator_id=owner[0]))
            db.add(SupportOperatorGrant(operator_id=owner[0], capability="simulation.start"))
            await db.commit()

        propose_resp = await owner_client.post(
            f"{API}/cases/{case_id}/account-actions",
            json={
                "kind": "permission_view",
                "case_revision": 1,
                "user_revision": 0,
                "user_id": str(subject_id),
                "reason_code": "permission_triage",
                "permission_key": "reports:view",
                "reason": "Single owner verifying permission view projection.",
            },
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert propose_resp.status_code == 201, propose_resp.text
        action = propose_resp.json()
        assert action["authorization_mode"] == "single_owner"

        exec_opts = await owner_client.post(
            f"{API}/cases/{case_id}/account-actions/{action['id']}/execute/options"
        )
        assert exec_opts.status_code == 200
        exec_resp = await owner_client.post(
            f"{API}/cases/{case_id}/account-actions/{action['id']}/execute",
            json={
                **sign(exec_opts.json(), *owner, counter=2),
                "expected_digest": action["digest"],
            },
        )
        assert exec_resp.status_code == 200

        read_resp = await owner_client.get(
            f"{API}/views/{action['id']}/projection/permission-explanation"
        )
        assert read_resp.status_code == 200, read_resp.text
        assert read_resp.json()["allowed"] is False
        assert read_resp.json()["permission_key"] == "reports:view"


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_directory_authorization_user360_redaction_and_mep_access_explanation() -> None:
    """Verify V-01, V-02, V-03, V-05, V-06, V-07, V-08."""
    await skip_if_database_unavailable()
    async with (
        client() as case_only_client,
        client() as dir_client,
        client(base_url="https://portal.garrisons.lk") as business_client,
    ):
        case_op = await login(case_only_client, custodian=False)
        dir_op = await login(dir_client, custodian=False)

        await grant_capabilities(case_op[0], "directory.read", "cases.manage")
        await grant_capabilities(dir_op[0], "company.directory.read")

        mep_user_id, assigned_proj_id, CreatorOnlyProjId, other_case_id = (
            uuid4(),
            uuid4(),
            uuid4(),
            uuid4(),
        )
        dept_id, pos_id, emp_id = uuid4(), uuid4(), uuid4()
        suffix = uuid4().hex[:6]

        async with AsyncSessionLocal() as db:
            db.add(
                User(
                    id=mep_user_id,
                    full_name=f"Nuwan Perera %_{suffix}",
                    email=f"nuwan.{suffix}@garrisons.lk",
                    employee_code=f"EMP-MEP-{suffix}",
                    phone="0771234567",
                    designation="Senior MEP Manager",
                    role=ROLE_MEP_PROJECT_MANAGER,
                    password_hash="secret-bcrypt-hash-do-not-disclose",
                    is_active=True,
                )
            )
            await db.flush()
            db.add(
                HrDepartment(
                    id=dept_id,
                    code=f"D-{suffix}",
                    name=f"MEP Dept {suffix}",
                )
            )
            db.add(
                HrPosition(
                    id=pos_id,
                    code=f"P-{suffix}",
                    title="MEP Manager",
                    department_id=dept_id,
                )
            )
            await db.flush()
            db.add(
                HrEmployee(
                    id=emp_id,
                    employee_code=f"HR-MEP-{suffix}",
                    user_id=mep_user_id,
                    first_name="Nuwan",
                    last_name=f"Perera %_{suffix}",
                    full_name=f"Nuwan Perera %_{suffix}",
                    work_email=f"nuwan.{suffix}@garrisons.lk",
                    department_id=dept_id,
                    position_id=pos_id,
                    employment_category="permanent",
                    employment_status="active",
                    join_date=date(2025, 1, 10),
                )
            )
            db.add_all(
                [
                    Project(
                        id=assigned_proj_id,
                        name=f"Assigned Tower {suffix}",
                        code=f"ATW-{suffix}",
                        status="active",
                        scope_of_work="Assigned project",
                        target_end_date=date(2028, 12, 31),
                        created_by=mep_user_id,
                    ),
                    Project(
                        id=CreatorOnlyProjId,
                        name=f"Priced Planning Setup {suffix}",
                        code=f"PPS-{suffix}",
                        status="planning",
                        scope_of_work="Created by MEP without membership",
                        target_end_date=date(2029, 6, 30),
                        created_by=mep_user_id,
                    ),
                ]
            )
            await db.flush()
            db.add(
                ProjectMember(
                    project_id=assigned_proj_id,
                    user_id=mep_user_id,
                    role_in_project="MEP Lead",
                )
            )
            db.add(
                SupportCase(
                    id=other_case_id,
                    owner_id=case_op[0],
                    external_ref=f"case-{other_case_id.hex[:8]}",
                    reason_code="access",
                    status="open",
                    severity="low",
                )
            )
            await db.flush()
            db.add(SupportCaseMember(case_id=other_case_id, operator_id=case_op[0]))
            await db.commit()

        # V-01: Business token on portal host or support host is rejected.
        b_token, _ = create_access_token(mep_user_id, ROLE_MEP_PROJECT_MANAGER)
        assert (
            await business_client.get(
                f"{API}/company/users", headers={"Authorization": f"Bearer {b_token}"}
            )
        ).status_code == 404
        assert (
            await dir_client.get(
                f"{API}/company/users",
                headers={"Authorization": f"Bearer {b_token}", "Cookie": ""},
            )
        ).status_code == 401

        # V-02: Case-only directory.read cannot search company-wide directory.
        assert (await case_only_client.get(f"{API}/company/users")).status_code == 403
        assert (
            await case_only_client.get(f"{API}/company/users/{mep_user_id}")
        ).status_code == 403

        # V-03: Company directory reader cannot open another operator's support case.
        assert (await dir_client.get(f"{API}/cases/{other_case_id}")).status_code in {403, 404}

        # V-07: Wildcard search (% and _) is escaped and paginated safely.
        search_resp = await dir_client.get(
            f"{API}/company/users", params={"search": f"%_{suffix}", "limit": 10}
        )
        assert search_resp.status_code == 200, search_resp.text
        items = search_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == str(mep_user_id)
        assert items[0]["assigned_project_count"] == 1
        assert items[0]["has_linked_employee"] is True
        assert f"nuwan.{suffix}@garrisons.lk" not in search_resp.text

        # V-08: User 360 profile masks phone/email and excludes password hash & private HR fields.
        prof_resp = await dir_client.get(f"{API}/company/users/{mep_user_id}")
        assert prof_resp.status_code == 200, prof_resp.text
        prof = prof_resp.json()
        assert prof["has_linked_employee"] is True
        assert prof["employee_status"] == "active"
        assert prof["phone_masked"] == "***-4567"
        assert "0771234567" not in prof_resp.text
        assert "secret-bcrypt-hash-do-not-disclose" not in prof_resp.text

        # V-05: Distinguish assigned project vs MEP planning creator-only project.
        acc_assigned = await dir_client.get(
            f"{API}/company/users/{mep_user_id}/access",
            params={"project_id": str(assigned_proj_id)},
        )
        assert acc_assigned.status_code == 200
        assert acc_assigned.json()["focused_project_explanation"]["allowed"] is True
        assert acc_assigned.json()["focused_project_explanation"]["category"] == "allowed"

        acc_creator_only = await dir_client.get(
            f"{API}/company/users/{mep_user_id}/access",
            params={"project_id": str(CreatorOnlyProjId)},
        )
        assert acc_creator_only.status_code == 200
        focused = acc_creator_only.json()["focused_project_explanation"]
        assert focused["allowed"] is False
        assert focused["category"] == "no_project_membership"
        assert "created this project during setup" in focused["explanation"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_command_lifecycle_create_role_membership_sessions_recovery_and_immutability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify V-09..V-30, V-36..V-38, V-48..V-50 end-to-end against PostgreSQL."""
    await skip_if_database_unavailable()
    sent_emails: list[dict[str, object]] = []
    mail_should_fail = {"fail": False}

    settings = Settings(
        app_env="test",
        support_portal_enabled=True,
        support_custody_mode="single_owner",
        support_recovery_key=SecretStr("company-admin-recovery-key-at-least-32-bytes"),
    )
    monkeypatch.setattr("app.services.support_identity.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.support_admin_policy.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.support_account_directory.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.support_admin_commands.get_settings", lambda: settings)

    def fake_send(_service: object, *, recipients: list[str], subject: str, body: str) -> int:
        if mail_should_fail["fail"]:
            raise EmailDeliveryError("Simulated SMTP failure")
        sent_emails.append({"recipients": recipients, "subject": subject, "body": body})
        return 1

    monkeypatch.setattr("app.services.support_admin_commands.EmailService.send", fake_send)

    async with client() as owner_client, client() as second_session_client:
        owner = await login(owner_client, custodian=False)
        sign_counter = 2

        def next_counter() -> int:
            nonlocal sign_counter
            val = sign_counter
            sign_counter += 1
            return val

        director_a, director_b, project_id = uuid4(), uuid4(), uuid4()
        suffix = uuid4().hex[:6]

        async with AsyncSessionLocal() as db:
            await db.execute(delete(SupportBootstrap))
            db.add(
                SupportBootstrap(
                    id=1,
                    first_id=owner[0],
                    custody_mode="single_owner",
                    approval_digest="b" * 64,
                    started_at=utc_now(),
                    activated_at=utc_now(),
                )
            )
            for idx, did in enumerate((director_a, director_b), start=1):
                db.add(
                    User(
                        id=did,
                        full_name=f"Director {idx} {suffix}",
                        email=f"director{idx}.{suffix}@garrisons.lk",
                        employee_code=f"DIR-{idx}-{suffix}",
                        role=ROLE_MANAGING_DIRECTOR,
                        password_hash="usable-director-password-hash",
                        is_active=True,
                    )
                )
            db.add(
                Project(
                    id=project_id,
                    name=f"Harbour Project {suffix}",
                    code=f"HRB-{suffix}",
                    status="active",
                    scope_of_work="Harbour construction",
                    target_end_date=date(2029, 12, 31),
                )
            )
            await db.commit()

        await grant_capabilities(
            owner[0], *COMPANY_CONTROL_CAPABILITIES, "config.read", "cases.manage"
        )

        # 1. V-10 & V-23: Missing required fields or super_admin role rejected with 422.
        bad_role = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "create_business_account",
                "email": f"badrole.{suffix}@garrisons.lk",
                "full_name": "Bad Role User",
                "role": "super_admin",
                "employee_code": f"BAD-{suffix}",
                "phone": "0770001111",
                "reason_code": "account_provisioning",
                "reason": "Testing role assignment ceiling enforcement.",
            },
        )
        assert bad_role.status_code == 422

        # 2. V-12 & V-13: Plan idempotency & conflict, then passkey execution (J-02).
        create_key = str(uuid4())
        create_payload = {
            "command_kind": "create_business_account",
            "email": f"kasun.{suffix}@garrisons.lk",
            "full_name": f"Kasun Silva {suffix}",
            "role": ROLE_SITE_SUPERVISOR,
            "employee_code": f"SUP-{suffix}",
            "phone": "0779998888",
            "designation": "Site Supervisor",
            "project_assignments": [
                {
                    "project_id": str(project_id),
                    "expected_project_revision": 1,
                    "role_in_project": "Field Supervisor",
                }
            ],
            "reason_code": "account_provisioning",
            "reason": "Onboarding new site supervisor for Harbour Project.",
        }
        plan1 = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": create_key},
            json=create_payload,
        )
        assert plan1.status_code == 201, plan1.text
        plan1_data = plan1.json()
        assert plan1_data["status"] == "planned"

        # Same key + same payload returns identical command plan (V-12).
        plan1_replay = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": create_key},
            json=create_payload,
        )
        assert plan1_replay.status_code == 201
        assert plan1_replay.json()["command_id"] == plan1_data["command_id"]

        # Same key + different payload returns 409 (V-13).
        plan1_conflict = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": create_key},
            json={**create_payload, "full_name": "Different Person"},
        )
        assert plan1_conflict.status_code == 409

        # Execute account creation with passkey proof.
        exec_create = await execute_planned_command(
            owner_client, owner, plan1_data, counter=next_counter()
        )
        assert exec_create.status_code == 200, exec_create.text
        created_receipt = exec_create.json()
        assert created_receipt["status"] == "succeeded"
        assert created_receipt["result"]["account_state"] == "created"
        assert created_receipt["result"]["invitation_state"] == "accepted"
        assert len(sent_emails) == 1
        # V-27: Secret OTP is never present in the API response.
        sent_body = str(sent_emails[-1]["body"])
        otp_code = sent_body.split("activate your password: ")[1].splitlines()[0].strip()
        assert otp_code not in exec_create.text

        created_user_id = UUID(created_receipt["result"]["user_id"])

        # V-11: On mail transport failure, account persists with delivery_failed status.
        mail_should_fail["fail"] = True
        plan_fail_mail = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "create_business_account",
                "email": f"nomail.{suffix}@garrisons.lk",
                "full_name": f"No Mail User {suffix}",
                "role": ROLE_QUANTITY_SURVEYOR,
                "employee_code": f"QS-{suffix}",
                "phone": "0772223333",
                "project_assignments": [],
                "reason_code": "account_provisioning",
                "reason": "Testing invitation transport failure persistence.",
            },
        )
        assert plan_fail_mail.status_code == 201
        exec_fail_mail = await execute_planned_command(
            owner_client, owner, plan_fail_mail.json(), counter=next_counter()
        )
        assert exec_fail_mail.status_code == 200
        assert exec_fail_mail.json()["status"] == "delivery_failed"
        assert exec_fail_mail.json()["result"]["account_state"] == "created"
        assert exec_fail_mail.json()["result"]["invitation_state"] == "failed"
        mail_should_fail["fail"] = False

        # 3. Role change and project membership revocation (J-03, V-14, V-24, V-25).
        role_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "change_business_role",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 0,
                "new_role": ROLE_GROUP_PROJECT_MANAGER,
                "reason_code": "role_adjustment",
                "reason": "Promoting supervisor to Group Project Manager.",
            },
        )
        assert role_plan.status_code == 201
        assert "projects:manage" in role_plan.json()["after"]["gained_permissions"]
        role_exec = await execute_planned_command(
            owner_client, owner, role_plan.json(), counter=next_counter()
        )
        assert role_exec.status_code == 200
        assert role_exec.json()["result"]["new_role"] == ROLE_GROUP_PROJECT_MANAGER
        assert role_exec.json()["result"]["access_revision"] == 1

        # Stale revision check (V-14).
        stale_role_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "change_business_role",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 0,
                "new_role": ROLE_SITE_SUPERVISOR,
                "reason_code": "role_adjustment",
                "reason": "Stale user revision must be rejected.",
            },
        )
        assert stale_role_plan.status_code == 409

        # Revoke project membership (project revision is now 2 after creation assignment).
        mem_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "change_project_membership",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 1,
                "project_id": str(project_id),
                "expected_project_revision": 2,
                "action": "revoke",
                "reason_code": "project_membership",
                "reason": "Rotating project manager off Harbour Project.",
            },
        )
        assert mem_plan.status_code == 201
        mem_exec = await execute_planned_command(
            owner_client, owner, mem_plan.json(), counter=next_counter()
        )
        assert mem_exec.status_code == 200
        assert mem_exec.json()["result"]["project_revision"] == 3
        assert mem_exec.json()["result"]["access_revision"] == 2

        # 4. Session inventory and targeted vs all-session revocation (J-05, V-28, V-29).
        sess_keep, sess_revoke, other_user_sess = uuid4(), uuid4(), uuid4()
        expires = utc_now() + timedelta(hours=2)
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    AuthSession(id=sess_keep, user_id=created_user_id, expires_at=expires),
                    AuthSession(id=sess_revoke, user_id=created_user_id, expires_at=expires),
                    AuthSession(id=other_user_sess, user_id=director_a, expires_at=expires),
                ]
            )
            await db.flush()
            db.add_all(
                [
                    AuthRefreshToken(
                        user_id=created_user_id,
                        session_id=sess_keep,
                        token_hash=f"hash-keep-{sess_keep}",
                        expires_at=expires,
                    ),
                    AuthRefreshToken(
                        user_id=created_user_id,
                        session_id=sess_revoke,
                        token_hash=f"hash-revoke-{sess_revoke}",
                        expires_at=expires,
                    ),
                ]
            )
            await db.commit()

        inv_resp = await owner_client.get(f"{API}/company/users/{created_user_id}/sessions")
        assert inv_resp.status_code == 200
        assert inv_resp.json()["active_session_count"] == 2
        assert "hash-keep" not in inv_resp.text

        # V-28: Revoking a session belonging to another user is rejected with 404.
        wrong_sess = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "revoke_business_session",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 2,
                "scope": "selected",
                "session_id": str(other_user_sess),
                "reason_code": "suspected_access",
                "reason": "Testing cross-user session ownership check.",
            },
        )
        assert wrong_sess.status_code == 404

        # Revoke only sess_revoke; sess_keep stays active.
        sel_sess_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "revoke_business_session",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 2,
                "scope": "selected",
                "session_id": str(sess_revoke),
                "reason_code": "suspected_access",
                "reason": "Revoking single suspicious session.",
            },
        )
        assert sel_sess_plan.status_code == 201
        sel_sess_exec = await execute_planned_command(
            owner_client, owner, sel_sess_plan.json(), counter=next_counter()
        )
        assert sel_sess_exec.status_code == 200
        inv_after = (
            await owner_client.get(f"{API}/company/users/{created_user_id}/sessions")
        ).json()
        assert inv_after["active_session_count"] == 1

        # 5. Protected solo recovery denial vs standard user recovery & destination guard (J-04).
        prot_rec = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "request_account_recovery",
                "target_user_id": str(director_a),
                "expected_user_revision": 0,
                "reason_code": "verified_user_report",
                "reason": "Protected director solo recovery must be denied by policy.",
            },
        )
        assert prot_rec.status_code == 403
        assert prot_rec.json()["error_code"] == "PROTECTED_TARGET_SOLO_RECOVERY_DENIED"

        # V-26: Plan recovery, then mutate email before execution -> rejected with 409.
        rec_plan_stale = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "request_account_recovery",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 2,
                "reason_code": "verified_user_report",
                "reason": "User requested account recovery instructions.",
            },
        )
        assert rec_plan_stale.status_code == 201
        async with AsyncSessionLocal() as db:
            u = await db.get(User, created_user_id)
            assert u is not None
            u.email = f"changed.{suffix}@garrisons.lk"
            await db.commit()
        assert (
            await owner_client.post(
                f"{API}/company/commands/{rec_plan_stale.json()['command_id']}/proof/options"
            )
        ).status_code == 409

        # Restore email and execute valid recovery.
        async with AsyncSessionLocal() as db:
            u = await db.get(User, created_user_id)
            assert u is not None
            u.email = f"kasun.{suffix}@garrisons.lk"
            await db.commit()
        rec_plan_ok = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "request_account_recovery",
                "target_user_id": str(created_user_id),
                "expected_user_revision": 2,
                "reason_code": "verified_user_report",
                "reason": "Verified recipient recovery request.",
            },
        )
        assert rec_plan_ok.status_code == 201
        rec_exec = await execute_planned_command(
            owner_client, owner, rec_plan_ok.json(), counter=next_counter()
        )
        assert rec_exec.status_code == 200
        assert rec_exec.json()["status"] == "succeeded"
        assert rec_exec.json()["result"]["delivery_state"] == "accepted"

        # 6. Anti-lockout guard on disabling directors (V-21) and bulk lifecycle (V-48).
        # Query any pre-existing usable directors so we test disabling ALL usable directors cleanly.
        async with AsyncSessionLocal() as db:
            other_directors = (
                await db.execute(
                    select(User).where(
                        User.id.not_in([director_a, director_b]),
                        User.role.in_(["managing_director", "operations_director"]),
                        User.is_active.is_(True),
                        User.deleted_at.is_(None),
                        User.password_hash.is_not(None),
                    )
                )
            ).scalars().all()
            other_director_ids = [d.id for d in other_directors]
            if other_director_ids:
                await db.execute(
                    update(User)
                    .where(User.id.in_(other_director_ids))
                    .values(is_active=False)
                )
                await db.commit()
        try:
            bulk_both_directors = await owner_client.post(
                f"{API}/company/commands/plan",
                headers={"Idempotency-Key": str(uuid4())},
                json={
                    "command_kind": "bulk_account_lifecycle",
                    "operation": "disable",
                    "targets": [
                        {"user_id": str(director_a), "expected_user_revision": 0},
                        {"user_id": str(director_b), "expected_user_revision": 0},
                    ],
                    "reason_code": "suspected_access",
                    "reason": "Testing bulk anti-lockout across all active directors.",
                },
            )
            assert bulk_both_directors.status_code == 409
            assert bulk_both_directors.json()["error_code"] == "LAST_ACCESS_MANAGER_REQUIRED"
        finally:
            if other_director_ids:
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(User)
                        .where(User.id.in_(other_director_ids))
                        .values(is_active=True)
                    )
                    await db.commit()

        # Bulk revoke_sessions on created_user_id succeeds.
        bulk_ok_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "bulk_account_lifecycle",
                "operation": "revoke_sessions",
                "targets": [{"user_id": str(created_user_id), "expected_user_revision": 3}],
                "reason_code": "suspected_access",
                "reason": "Rotating sessions for field supervisor.",
            },
        )
        assert bulk_ok_plan.status_code == 201
        bulk_ok_exec = await execute_planned_command(
            owner_client, owner, bulk_ok_plan.json(), counter=next_counter()
        )
        assert bulk_ok_exec.status_code == 200
        assert bulk_ok_exec.json()["result"]["succeeded_count"] == 1

        # 7. Safe settings editor (T-24, V-36).
        settings_list_resp = await owner_client.get(f"{API}/company/settings")
        assert settings_list_resp.status_code == 200
        banner_item = next(
            s for s in settings_list_resp.json()["items"] if s["key"] == "support_banner_notice"
        )
        banner_rev = int(banner_item["revision"])

        forbidden_setting = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "update_safe_setting",
                "setting_key": "log_purge_enabled",
                "expected_revision": 0,
                "value": "true",
                "reason_code": "operational_configuration",
                "reason": "Attempting to toggle forbidden audit purge setting.",
            },
        )
        assert forbidden_setting.status_code == 422
        assert forbidden_setting.json()["error_code"] == "SUPPORT_SETTING_NOT_ALLOWLISTED"

        safe_setting_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "update_safe_setting",
                "setting_key": "support_banner_notice",
                "expected_revision": banner_rev,
                "value": "Scheduled maintenance Sunday 02:00 UTC",
                "reason_code": "operational_configuration",
                "reason": "Posting operational maintenance banner.",
            },
        )
        assert safe_setting_plan.status_code == 201
        safe_setting_exec = await execute_planned_command(
            owner_client, owner, safe_setting_plan.json(), counter=next_counter()
        )
        assert safe_setting_exec.status_code == 200
        banner_rev += 1
        ctx_resp = await owner_client.get(f"{API}/company/context")
        assert ctx_resp.status_code == 200
        assert (
            ctx_resp.json()["banner_notice"]
            == "Scheduled maintenance Sunday 02:00 UTC"
        )

        # 8. Registered non-sensitive data inspector (T-27, V-49).
        cat_resp = await owner_client.get(f"{API}/company/data-inspector/entities")
        assert cat_resp.status_code == 200
        proj_inspect = await owner_client.get(
            f"{API}/company/data-inspector/projects", params={"search": f"HRB-{suffix}"}
        )
        assert proj_inspect.status_code == 200
        assert proj_inspect.json()["total"] == 1

        for forbidden_entity in ("users", "hr_employees", "hr_employee_private", "auth_sessions"):
            assert (
                await owner_client.get(f"{API}/company/data-inspector/{forbidden_entity}")
            ).status_code == 404

        # 9. Safe job retry (T-26, V-50).
        retry_batch_id, retry_outbox_id = uuid4(), uuid4()
        csv_data = b"item_code,location_code,quantity,notes\nA,B,1,test\n"
        ciphertext, key_id = encrypt_import_payload_with_key_id(csv_data)
        async with AsyncSessionLocal() as db:
            db.add(
                ImportBatch(
                    id=retry_batch_id,
                    template_type="opening_stock",
                    file_name="retry.csv",
                    status="failed",
                    created_by=director_a,
                )
            )
            db.add(
                TaskOutbox(
                    id=retry_outbox_id,
                    dedupe_key=import_outbox_dedupe_key(retry_batch_id),
                    task_name="run_import_async",
                    args_json=[str(retry_batch_id), str(director_a)],
                    kwargs_json={
                        "template_type": "opening_stock",
                        "file_name": "retry.csv",
                        "content_sha256": sha256(csv_data).hexdigest(),
                        "content_ciphertext": ciphertext,
                        "content_key_id": key_id,
                    },
                    status="failed",
                    attempts=5,
                )
            )
            await db.commit()

        retry_plan = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "retry_safe_job",
                "job_source": "task_outbox",
                "job_id": str(retry_outbox_id),
                "reason_code": "operational_recovery",
                "reason": "Re-queuing failed opening stock import after broker recovery.",
            },
        )
        assert retry_plan.status_code == 201
        retry_exec = await execute_planned_command(
            owner_client, owner, retry_plan.json(), counter=next_counter()
        )
        assert retry_exec.status_code == 200
        assert retry_exec.json()["result"]["status"] == "pending"

        # 10. Contextual case diagnosis (T-22) and database immutability triggers (V-38).
        diag_resp = await owner_client.post(
            f"{API}/company/users/{created_user_id}/diagnose-case",
            json={
                "reason": "Opening contextual diagnosis case from User 360 profile.",
                "project_id": str(project_id),
            },
        )
        assert diag_resp.status_code == 201
        assert diag_resp.json()["subject_user_id"] == str(created_user_id)
        assert str(project_id) in diag_resp.json()["linked_project_ids"]

        # 11. V-15 (tampered digest), V-16 (replay & cross-session), V-17 (grant revocation).
        guard_plan_resp = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "update_safe_setting",
                "setting_key": "support_banner_notice",
                "expected_revision": banner_rev,
                "value": "Updated maintenance window",
                "reason_code": "operational_configuration",
                "reason": "Testing proof binding, replay, and grant-epoch guards.",
            },
        )
        assert guard_plan_resp.status_code == 201
        guard_plan = guard_plan_resp.json()
        guard_cmd_id = guard_plan["command_id"]

        # V-16b: Different operator session cannot request proof for another session's command.
        second_op = await login(second_session_client, custodian=False)
        await grant_capabilities(second_op[0], *COMPANY_CONTROL_CAPABILITIES)
        assert (
            await second_session_client.post(
                f"{API}/company/commands/{guard_cmd_id}/proof/options"
            )
        ).status_code == 403

        # V-15: Tampered expected_plan_sha256 is rejected with 409.
        tamper_opts = await owner_client.post(
            f"{API}/company/commands/{guard_cmd_id}/proof/options"
        )
        assert tamper_opts.status_code == 200
        tamper_proof = {
            **sign(tamper_opts.json(), *owner, counter=next_counter()),
            "expected_plan_sha256": "0" * 64,
        }
        tamper_exec = await owner_client.post(
            f"{API}/company/commands/{guard_cmd_id}/execute", json=tamper_proof
        )
        assert tamper_exec.status_code == 409

        # Execute with a fresh valid proof, then attempt to replay that same proof (V-16a).
        valid_opts = await owner_client.post(
            f"{API}/company/commands/{guard_cmd_id}/proof/options"
        )
        assert valid_opts.status_code == 200
        valid_proof = {
            **sign(valid_opts.json(), *owner, counter=next_counter()),
            "expected_plan_sha256": guard_plan["plan_sha256"],
        }
        first_exec = await owner_client.post(
            f"{API}/company/commands/{guard_cmd_id}/execute", json=valid_proof
        )
        assert first_exec.status_code == 200
        banner_rev += 1
        replay_exec = await owner_client.post(
            f"{API}/company/commands/{guard_cmd_id}/execute", json=valid_proof
        )
        assert replay_exec.status_code == 409

        # V-17: Revoking capability between plan and execute rejects proof/execute with 403,
        # and incrementing grant_epoch immediately invalidates the session with 401.
        epoch_plan_resp = await owner_client.post(
            f"{API}/company/commands/plan",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "command_kind": "update_safe_setting",
                "setting_key": "support_banner_notice",
                "expected_revision": banner_rev,
                "value": "Epoch guard test",
                "reason_code": "operational_configuration",
                "reason": "Testing capability revocation and grant_epoch guard before execute.",
            },
        )
        assert epoch_plan_resp.status_code == 201
        epoch_plan = epoch_plan_resp.json()
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(SupportOperatorGrant).where(
                    SupportOperatorGrant.operator_id == owner[0],
                    SupportOperatorGrant.capability == "company.settings.manage",
                )
            )
            await db.commit()
        assert (
            await owner_client.post(
                f"{API}/company/commands/{epoch_plan['command_id']}/proof/options"
            )
        ).status_code == 403

        async with AsyncSessionLocal() as db:
            op_row = await db.get(SupportOperator, owner[0])
            assert op_row is not None
            op_row.grant_epoch += 1
            await db.commit()
        assert (
            await owner_client.post(
                f"{API}/company/commands/{epoch_plan['command_id']}/proof/options"
            )
        ).status_code == 401

        # V-38: Completed command and event rows are immutable in PostgreSQL.
        completed_cmd_id = UUID(safe_setting_exec.json()["command_id"])
        async with AsyncSessionLocal() as db:
            with pytest.raises(DBAPIError, match="immutable"):
                await db.execute(
                    update(SupportAdminCommand)
                    .where(SupportAdminCommand.id == completed_cmd_id)
                    .values(reason="Tampered reason")
                )
            await db.rollback()
            with pytest.raises(DBAPIError, match="append-only"):
                await db.execute(
                    delete(SupportAdminCommandEvent).where(
                        SupportAdminCommandEvent.command_id == completed_cmd_id
                    )
                )
            await db.rollback()
