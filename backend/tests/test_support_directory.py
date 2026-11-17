from datetime import date
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from app.config import Settings
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.support_case_actions import SupportCaseProject
from app.models.support_cases import SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportDirectoryRead
from app.models.user import User
from app.utils.permissions import ROLE_HR_EXECUTIVE
from app.utils.recovery_destination import recovery_destination_digest
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_cases import CASES, case_operator
from tests.test_support_custody import login
from tests.test_support_identity import client, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_reviewed_subject_controls_masked_reads_and_revocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    settings = Settings(
        support_recovery_key=SecretStr("disposable-directory-recovery-key-only")
    )
    monkeypatch.setattr("app.services.support_directory.get_settings", lambda: settings)
    async with client() as owner, client() as reviewer, client() as outsider:
        owner_id = await case_operator(owner)
        approver = await login(reviewer, custodian=False)
        outsider_id, _, _ = await login(outsider, custodian=False)
        user_id = uuid4()
        email = f"synthetic-{user_id.hex}@example.com"
        binding = recovery_destination_digest(settings, user_id, email)
        assert binding is not None
        async with AsyncSessionLocal() as session:
            session.add_all(
                SupportOperatorGrant(operator_id=operator, capability="directory.read")
                for operator in (owner_id, approver[0], outsider_id)
            )
            session.add(SupportOperatorGrant(operator_id=approver[0], capability="cases.manage"))
            session.add(
                User(
                    id=user_id,
                    email=email,
                    full_name="Synthetic Employee",
                    role=ROLE_HR_EXECUTIVE,
                    employee_code="SYN-TEST",
                    phone="555-private-phone",
                    password_hash="private-marker",
                    recovery_email_digest=binding,
                    recovery_email_verified_at=utc_now(),
                )
            )
            await session.flush()
            session.add(
                ActivityLog(
                    user_id=user_id,
                    action="auth.login_failed",
                    ip_address="192.0.2.4",
                    user_agent="private-agent",
                    comments="private-marker",
                )
            )
            await session.commit()

        response = await owner.post(
            CASES,
            json={
                "external_ref": f"directory-{uuid4()}",
                "severity": "medium",
                "reason_code": "access",
            },
        )
        assert response.status_code == 201, response.text
        case_id = UUID(response.json()["id"])
        approved_project_id, other_project_id = uuid4(), uuid4()
        approved_membership_id, other_membership_id = uuid4(), uuid4()
        async with AsyncSessionLocal() as session:
            session.add(SupportCaseMember(case_id=case_id, operator_id=approver[0]))
            session.add_all(
                Project(
                    id=project_id, name="Synthetic", code=project_id.hex[:20],
                    scope_of_work="Directory fixture", target_end_date=date(2035, 1, 1),
                )
                for project_id in (approved_project_id, other_project_id)
            )
            await session.flush()
            session.add(SupportCaseProject(case_id=case_id, project_id=approved_project_id))
            session.add_all([
                ProjectMember(
                    id=approved_membership_id, project_id=approved_project_id, user_id=user_id,
                ),
                ProjectMember(id=other_membership_id, project_id=other_project_id, user_id=user_id),
            ])
            await session.commit()

        case = f"{CASES}/{case_id}"
        endpoint = f"{case}/accounts/{user_id}"
        lookup = f"{case}/accounts"
        assert (await owner.get(endpoint)).status_code == 404
        assert (await owner.get(lookup)).status_code == 404
        for revision, kind in ((1, "subject_set"), (2, "subject_remove")):
            payload = {"kind": kind}
            if kind == "subject_set":
                payload["subject_user_id"] = str(user_id)
            request = await owner.post(
                f"{case}/actions", json=payload, headers={"If-Match": f'"{revision}"'}
            )
            assert request.status_code == 201, request.text
            path = f"{case}/actions/{request.json()['id']}"
            assert (await owner.post(f"{path}/options")).status_code == 403
            assert (await outsider.post(f"{path}/options")).status_code == 404
            options = await reviewer.post(f"{path}/options")
            assert options.status_code == 200, options.text
            assert options.json()["proposal"]["subject_user_id"] == str(user_id)
            decision = await reviewer.post(
                f"{path}/apply", json=sign(options.json(), *approver, counter=revision + 1)
            )
            assert decision.status_code == 200, decision.text
            read = await owner.get(endpoint)
            if kind == "subject_remove":
                assert read.status_code == 404
                assert (await owner.get(lookup)).status_code == 404
                continue
            assert read.status_code == 200, read.text
            assert read.headers["cache-control"] == "no-store"
            result = read.json()
            assert result["email_masked"] == "s***@example.com"
            assert result["recovery_destination_verified"] is None
            assert result["employee_code"] == "SYN-TEST"
            assert result["membership_ids"] == [str(approved_membership_id)]
            assert result["recent_auth_events"][0]["category"] == "login_failed"
            found = await owner.get(lookup)
            assert found.status_code == 200 and found.json() == result
            assert found.headers["cache-control"] == "no-store"
            assert (await outsider.get(lookup)).status_code == 404
            for field, value in (
                ("email", email.upper()), ("employee_code", "syn-test"),
                ("name", "employee"), ("role", ROLE_HR_EXECUTIVE),
            ):
                selector = {"field": field, "value": value}
                matched = await owner.post(f"{lookup}/search", json=selector)
                assert matched.status_code == 200 and matched.json() == result
                assert (await outsider.post(f"{lookup}/search", json=selector)).status_code == 404
            for field, value in (("employee_code", "OTHER"), ("name", "unrelated")):
                selector = {"field": field, "value": value}
                assert (await owner.post(f"{lookup}/search", json=selector)).status_code == 404
            short = await owner.post(f"{lookup}/search", json={"field": "name", "value": "em"})
            assert short.status_code == 422
            for secret in (
                email,
                binding,
                "private-marker",
                "555-private-phone",
                "192.0.2.4",
                "private-agent",
            ):
                assert secret not in read.text
            async with AsyncSessionLocal() as session:
                session.add(
                    SupportOperatorGrant(operator_id=owner_id, capability="account.request")
                )
                await session.commit()
            ready = await owner.get(endpoint)
            assert ready.status_code == 200
            assert ready.json()["recovery_destination_verified"] is True
            assert binding not in ready.text and email not in ready.text
            async with AsyncSessionLocal() as session:
                user = await session.get(User, user_id)
                assert user is not None
                user.email = f"different-{user_id.hex}@example.com"
                await session.commit()
            changed = await owner.get(endpoint)
            assert changed.status_code == 200
            assert changed.json()["recovery_destination_verified"] is False
            current_email = f"different-{user_id.hex}@example.com"
            unverified = await owner.post(
                f"{lookup}/search", json={"field": "email", "value": current_email},
            )
            assert unverified.status_code == 404
            assert (await outsider.get(endpoint)).status_code == 404
            assert (await owner.get(f"{case}/accounts/{uuid4()}")).status_code == 404

        async with AsyncSessionLocal() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(SupportDirectoryRead)
                    .where(SupportDirectoryRead.case_id == case_id)
                )
                == 8
            )
