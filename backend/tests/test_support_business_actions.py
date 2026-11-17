import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select

from app.config import Settings
from app.database import AsyncSessionLocal
from app.models.auth import AuthOtpChallenge, AuthRefreshToken, AuthSession
from app.models.support_business_actions import SupportBusinessContact, SupportRecoveryDelivery
from app.models.support_case_audit import SupportCaseAuditRead
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_directory import SupportCaseSubject
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.services.email_service import EmailDeliveryError
from app.tasks.support_recovery import dispatch_recovery_deliveries
from app.utils.permissions import ROLE_MANAGING_DIRECTOR, ROLE_SITE_SUPERVISOR
from app.utils.recovery_destination import recovery_destination_digest, support_recovery_otp
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
@pytest.mark.parametrize(
    ("protected", "kind", "delivery_status"),
    [
        (False, "revoke_sessions", None),
        (True, "revoke_sessions", None),
        (False, "unlock", None),
        (False, "disable", None),
        (False, "reactivate", None),
        (True, "disable", None),
        (False, "recover", "accepted"),
        (True, "recover", "accepted"),
        (False, "recover", "unknown"),
        (False, "recover", "cancelled"),
    ],
)
async def test_business_session_revocation_with_live_review_and_protected_receipt(
    protected: bool,
    kind: str,
    delivery_status: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    settings = Settings(
        app_env="test",
        support_portal_enabled=True,
        support_recovery_key=SecretStr("disposable-support-issuance-key-for-testing"),
        frontend_base_url="https://portal.example.test",
    )
    monkeypatch.setattr("app.services.support_business_actions.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.auth_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.tasks.support_recovery.get_settings", lambda: settings)
    async with client() as maker, client() as first, client() as second, client() as outsider:
        a = await login(maker, custodian=False)
        b = await login(first)
        c = await login(second, custodian=False)
        d = await login(outsider, custodian=False)
        target, other, case, auth = uuid4(), uuid4(), uuid4(), uuid4()
        token_id, otp_id = uuid4(), uuid4()
        role = ROLE_MANAGING_DIRECTOR if protected else ROLE_SITE_SUPERVISOR
        expires = utc_now() + timedelta(hours=1)
        async with AsyncSessionLocal() as session:
            other_role = ROLE_MANAGING_DIRECTOR if protected else ROLE_SITE_SUPERVISOR
            for account, account_role in ((target, role), (other, other_role)):
                session.add(
                    User(
                        id=account,
                        full_name="Synthetic",
                        email=f"{account}@example.com",
                        role=account_role,
                        password_hash="synthetic-original-hash",
                        is_active=account != target or kind not in {"unlock", "reactivate"},
                        failed_login_attempts=4 if account == target and kind == "unlock" else 0,
                        locked_until=expires if account == target and kind == "unlock" else None,
                    )
                )
            session.add(
                SupportCase(
                    id=case,
                    status="open",
                    severity="medium",
                    owner_id=a[0],
                    external_ref=f"case-{case}",
                    reason_code="access",
                )
            )
            await session.flush()
            session.add(SupportCaseSubject(case_id=case, user_id=target))
            for operator in (a, b, c, d):
                session.add(
                    SupportOperatorGrant(operator_id=operator[0], capability="account.request")
                )
            session.add(SupportOperatorGrant(operator_id=a[0], capability="logs.audit"))
            for operator in (a, b, c):
                session.add(SupportCaseMember(case_id=case, operator_id=operator[0]))
            session.add(AuthSession(id=auth, user_id=target, expires_at=expires))
            await session.flush()
            session.add(
                AuthRefreshToken(
                    id=token_id,
                    user_id=target,
                    session_id=auth,
                    token_hash=f"synthetic-refresh-{token_id}",
                    expires_at=expires,
                )
            )
            session.add(
                AuthOtpChallenge(
                    id=otp_id,
                    user_id=target,
                    otp_hash="synthetic-otp",
                    expires_at=expires,
                )
            )
            await session.commit()

        root = f"{API}/cases/{case}/account-actions"
        key = {"Idempotency-Key": str(uuid4())}
        request = {
            "user_id": str(target),
            "user_revision": 0,
            "case_revision": 1,
            "kind": kind,
            "reason_code": "suspected_access",
            "reason": "Synthetic reproduction avoided token=private-synthetic-marker.",
        }
        assert (await outsider.post(root, json=request, headers=key)).status_code == 404
        assert (
            await maker.post(root, json={**request, "user_id": str(other)}, headers=key)
        ).status_code == 404
        if kind == "recover":
            blocked = await maker.post(root, json=request, headers=key)
            assert blocked.status_code == 409
            assert blocked.json()["error_code"] == "SUPPORT_RECOVERY_DESTINATION_UNVERIFIED"
            async with AsyncSessionLocal() as session:
                user = await session.get(User, target)
                assert user is not None
                user.recovery_email_digest = recovery_destination_digest(
                    settings, target, user.email
                )
                user.recovery_email_verified_at = utc_now()
                await session.commit()
        draft = await maker.post(root, json=request, headers=key)
        assert draft.status_code == 201, draft.text
        assert "private-synthetic-marker" not in draft.text
        assert (await maker.post(root, json=request, headers=key)).json() == draft.json()
        assert (
            await maker.post(
                root, json={**request, "reason": "Different request intentionally."}, headers=key
            )
        ).status_code == 409
        action = draft.json()
        assert action.get("recovery_destination_digest") is None
        path = f"{root}/{action['id']}"
        status_path = f"{path}/recovery-status"
        if kind == "recover":
            proposed = await maker.get(status_path)
            assert proposed.status_code == 200
            assert proposed.headers["cache-control"] == "no-store"
            assert proposed.json()["delivery_state"] == "not_queued"
            assert proposed.json()["reset_state"] == "not_issued"
            assert (await outsider.get(status_path)).status_code == 404
        else:
            assert (await maker.get(status_path)).status_code == 404
        assert (await maker.post(f"{path}/review/options")).status_code == 403
        assert (await maker.post(f"{path}/execute/options")).status_code == 409

        contact_ref = str(uuid4())

        async def options(browser: httpx.AsyncClient, phase: str, **fields: str) -> dict:
            response = await browser.post(f"{path}/{phase}/options", json=fields)
            assert response.status_code == 200, response.text
            assert response.json()["required_reviews"] == (2 if protected else 1)
            return response.json()

        denied_browser = second if protected else first
        assert (
            await denied_browser.post(f"{path}/review/options", json={"contact_ref": contact_ref})
        ).status_code == 403
        contact_fields = {"contact_ref": contact_ref} if protected else {}
        review = await options(first, "review", **contact_fields)
        proof = sign(review, *b, counter=2)
        if protected:
            assert review["contact_ref"] == contact_ref
            assert (
                await first.post(
                    f"{path}/review", json={**proof, "expected_digest": action["digest"]}
                )
            ).status_code == 409
            proof["expected_contact_ref"] = contact_ref
        assert (
            await first.post(f"{path}/review", json={**proof, "expected_digest": "0" * 64})
        ).status_code == 409
        accepted = await first.post(
            f"{path}/review", json={**proof, "expected_digest": action["digest"]}
        )
        assert accepted.status_code == 200, accepted.text
        assert (await first.post(f"{path}/execute/options")).status_code == 403
        if protected:
            assert (await maker.post(f"{path}/execute/options")).status_code == 409
            review = await options(second, "review")
            proof = sign(review, *c, counter=2)
            assert (
                await second.post(
                    f"{path}/review", json={**proof, "expected_digest": action["digest"]}
                )
            ).status_code == 200
            async with AsyncSessionLocal() as session:
                contact = await session.get(SupportBusinessContact, UUID(action["id"]))
                assert contact is not None and str(contact.contact_ref) == contact_ref
                assert contact.verifier_id == b[0] and contact.action_digest == action["digest"]
        if kind == "recover":
            async with AsyncSessionLocal() as session:
                user = await session.get(User, target)
                assert user is not None
                user.email = f"changed-{target}@example.com"
                await session.commit()
            assert (await maker.post(f"{path}/execute/options")).status_code == 409
            async with AsyncSessionLocal() as session:
                user = await session.get(User, target)
                assert user is not None
                user.email = f"{target}@example.com"
                await session.commit()
        execute = await options(maker, "execute")
        proof = {
            **sign(execute, *a, counter=2),
            "expected_digest": action["digest"],
        }
        if protected and kind == "disable":
            existing_check = UserRepository.has_other_usable_director

            async def no_other_director(_: UserRepository, target_id: UUID) -> bool:
                assert target_id == target
                return False

            monkeypatch.setattr(UserRepository, "has_other_usable_director", no_other_director)
            blocked = await maker.post(f"{path}/execute", json=proof)
            assert blocked.status_code == 409, blocked.text
            assert blocked.json()["error_code"] == "LAST_ACCESS_MANAGER_REQUIRED"
            async with AsyncSessionLocal() as session:
                unchanged = await session.get(User, target)
                auth_session_before = await session.get(AuthSession, auth)
                assert unchanged is not None and unchanged.is_active
                assert unchanged.access_revision == 0
                assert auth_session_before is not None and auth_session_before.revoked_at is None
            monkeypatch.setattr(UserRepository, "has_other_usable_director", existing_check)
        first_result, replay = await asyncio.gather(
            maker.post(f"{path}/execute", json=proof),
            maker.post(f"{path}/execute", json=proof),
        )
        assert sorted((first_result.status_code, replay.status_code)) == [200, 409]
        window = {
            "started_at": (utc_now() - timedelta(minutes=5)).isoformat(),
            "ended_at": (utc_now() + timedelta(seconds=1)).isoformat(),
        }
        audit_path = f"{API}/cases/{case}/audit"
        assert (await first.get(audit_path, params=window)).status_code == 403
        audit = await maker.get(audit_path, params=window)
        assert audit.status_code == 200, audit.text
        assert "synthetic-original-hash" not in audit.text
        assert "private-synthetic-marker" not in audit.text
        assert str(target) not in audit.text
        events = [event["event"] for event in audit.json()["events"]]
        assert ("status_read" in events) == (kind == "recover")
        assert [event for event in events if event != "status_read"] == (
            ["applied", "reviewed", "reviewed", "proposed"]
            if protected
            else ["applied", "reviewed", "proposed"]
        )
        limited = await maker.get(audit_path, params={**window, "limit": 1})
        assert limited.status_code == 200 and limited.json()["truncated"] is True
        assert (await maker.get(f"{API}/cases/{uuid4()}/audit", params=window)).status_code == 404
        assert (
            await maker.get(
                audit_path,
                params={
                    **window,
                    "started_at": (utc_now() - timedelta(days=2)).isoformat(),
                },
            )
        ).status_code == 422
        async with AsyncSessionLocal() as session:
            disclosed = await session.scalar(
                select(func.count())
                .select_from(SupportCaseAuditRead)
                .where(SupportCaseAuditRead.case_id == case)
            )
            assert disclosed == 2
            user = await session.get(User, target)
            auth_session = await session.get(AuthSession, auth)
            refresh = await session.get(AuthRefreshToken, token_id)
            otp = await session.get(AuthOtpChallenge, otp_id)
            assert user is not None and user.role == role
            assert user.password_hash == "synthetic-original-hash"
            assert auth_session is not None and refresh is not None and otp is not None
            if kind == "unlock":
                assert not user.is_active and user.access_revision == 0
                assert user.failed_login_attempts == 0 and user.locked_until is None
                assert auth_session.revoked_at is None and refresh.revoked_at is None
                assert otp.consumed_at is None
            else:
                assert user.is_active is (kind != "disable") and user.access_revision == 1
                assert auth_session.revoked_at is not None and refresh.revoked_at is not None
                assert otp.consumed_at is not None
            unrelated = await session.get(User, other)
            assert unrelated is not None and unrelated.access_revision == 0
            queue = await session.get(SupportRecoveryDelivery, UUID(action["id"]))
            if kind == "recover":
                assert queue is not None and queue.status == "pending"
                recovery = await session.get(AuthOtpChallenge, queue.challenge_id)
                assert recovery is not None and recovery.purpose == "support_password_reset"
                assert recovery.consumed_at is None
                recovery_code = support_recovery_otp(settings, recovery.id)
                assert recovery_code is not None and recovery.otp_hash != recovery_code
                attempt = {
                    "challenge_id": str(recovery.id),
                    "otp": recovery_code,
                    "new_password": "NewSynthetic123!",
                }
            else:
                assert queue is None
        if kind == "recover":
            success = first_result if first_result.status_code == 200 else replay
            assert attempt["challenge_id"] not in success.text
            pending = await maker.get(status_path)
            assert pending.status_code == 200
            assert pending.json()["delivery_state"] == "pending"
            assert pending.json()["reset_state"] == "waiting"
            assert set(pending.json()) == {
                "case_id",
                "action_id",
                "delivery_state",
                "reset_state",
                "queued_at",
                "delivery_resolved_at",
                "completed_at",
            }
            assert (
                attempt["challenge_id"] not in pending.text and "@example.com" not in pending.text
            )
            confirm = "/api/v1/auth/password-reset/confirm"
            assert (await maker.post(confirm, json=attempt)).status_code == 401
            sent = []

            def send_code(
                _service: object,
                *,
                recipients: list[str],
                subject: str,
                body: str,
                allow_fallback: bool,
            ) -> int:
                assert recipients == [f"{target}@example.com"] and not allow_fallback
                assert subject == "Your Garrisons recovery code"
                assert f"/password-reset#recovery={attempt['challenge_id']}" in body
                assert attempt["otp"] in body
                sent.append(1)
                if delivery_status == "unknown":
                    raise EmailDeliveryError("Synthetic uncertain outcome.")
                return 1

            monkeypatch.setattr("app.tasks.support_recovery.EmailService.send", send_code)
            if delivery_status == "cancelled":
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        delete(SupportOperatorGrant).where(
                            SupportOperatorGrant.operator_id == b[0],
                            SupportOperatorGrant.capability == "account.request",
                        )
                    )
                    await session.commit()
            counts = await asyncio.gather(
                dispatch_recovery_deliveries(), dispatch_recovery_deliveries()
            )
            assert sorted(counts) == [0, 1]
            assert await dispatch_recovery_deliveries() == 0
            assert len(sent) == (0 if delivery_status == "cancelled" else 1)
            async with AsyncSessionLocal() as session:
                delivery = await session.get(SupportRecoveryDelivery, UUID(action["id"]))
                assert delivery is not None and delivery.status == delivery_status
                assert delivery.dispatch_started_at and delivery.dispatch_finished_at
            delivery_view = await maker.get(status_path)
            assert delivery_view.status_code == 200
            assert delivery_view.json()["delivery_state"] == delivery_status
            assert delivery_view.json()["delivery_resolved_at"]
            if delivery_status != "accepted":
                assert delivery_view.json()["reset_state"] == "unavailable"
                if delivery_status == "cancelled":
                    assert (await first.get(status_path)).status_code == 403
                assert (await maker.post(confirm, json=attempt)).status_code == 401
                return
            assert delivery_view.json()["reset_state"] == "ready"
            finished = await maker.post(confirm, json=attempt)
            assert finished.status_code in {200, 204}, finished.text
            assert (await maker.post(confirm, json=attempt)).status_code == 401
            async with AsyncSessionLocal() as session:
                delivery = await session.get(SupportRecoveryDelivery, UUID(action["id"]))
                changed_user = await session.get(User, target)
                assert delivery is not None and delivery.completed_at is not None
                assert changed_user is not None and changed_user.access_revision == 2
                assert changed_user.password_hash != "synthetic-original-hash"
            completed = await maker.get(status_path)
            assert (
                completed.json()["reset_state"] == "completed" and completed.json()["completed_at"]
            )
