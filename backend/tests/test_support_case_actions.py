import asyncio
import json
from datetime import date
from hashlib import sha256
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.support_case_actions import (
    SupportCaseAction,
    SupportCaseActionEvent,
    SupportCaseProject,
)
from app.models.support_cases import SupportCaseEvent, SupportCaseMember, SupportOperatorGrant
from app.models.support_cli_proof import SupportCliProof
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_cases import CASES, case_operator
from tests.test_support_custody import login
from tests.test_support_identity import API, client, encoded, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_reviewed_membership_evidence_and_close_with_bound_passkey() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as custodian, client() as investigator:
        await case_operator(owner)
        custodian_key = await login(custodian)
        investigator_key = await login(investigator, custodian=False)
        operator_id = investigator_key[0]
        async with AsyncSessionLocal() as session:
            session.add_all(
                [
                    SupportOperatorGrant(operator_id=operator_id, capability="cases.manage"),
                    SupportOperatorGrant(operator_id=operator_id, capability="logs.runtime"),
                ]
            )
            await session.commit()

        created = await owner.post(
            CASES,
            json={
                "external_ref": f"incident-{uuid4()}",
                "severity": "high",
                "reason_code": "functional",
            },
        )
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
        case = f"{CASES}/{case_id}"

        async def propose(revision: int, kind: str, **extra: str) -> str:
            response = await owner.post(
                f"{case}/actions",
                headers={"If-Match": f'"{revision}"'},
                json={"kind": kind, **extra},
            )
            assert response.status_code == 201, response.text
            return f"{case}/actions/{response.json()['id']}"

        async def info(browser: httpx.AsyncClient, path: str) -> dict:
            response = await browser.post(f"{path}/options")
            assert response.status_code == 200, response.text
            return response.json()

        assert (await investigator.get(case)).status_code == 404
        add = await propose(1, "member_add", member_id=str(operator_id))
        assert (await owner.post(f"{add}/options")).status_code == 403
        assert (await investigator.post(f"{add}/options")).status_code == 403
        challenge = await info(custodian, add)
        proof = sign(challenge, *custodian_key, counter=2)
        one, two = await asyncio.gather(
            custodian.post(f"{add}/apply", json=proof),
            custodian.post(f"{add}/apply", json=proof),
        )
        assert sorted((one.status_code, two.status_code)) == [200, 409]
        assert (await investigator.get(case)).status_code == 200

        for revision, status in ((2, "investigating"), (3, "mitigated")):
            response = await owner.post(
                f"{case}/transitions",
                headers={"If-Match": f'"{revision}"'},
                json={"status": status, "reason_code": "functional"},
            )
            assert response.status_code == 200, response.text

        evidence_id, request_id = uuid4(), uuid4().hex
        async with AsyncSessionLocal() as session:
            session.add(
                ActivityLog(
                    id=evidence_id,
                    request_id=request_id,
                    entity_type="request",
                    action="http.request",
                    http_method="GET",
                    status_code=200,
                    comments="synthetic-private-marker",
                    created_at=utc_now(),
                )
            )
            await session.commit()
        premature = await propose(4, "verify", source_event_id=str(evidence_id))
        assert (await investigator.post(f"{premature}/options")).status_code == 409
        link = await propose(4, "evidence_link", source_event_id=str(evidence_id))
        assert (await custodian.post(f"{link}/options")).status_code == 404
        links = await info(investigator, link)
        assert links["proposal"]["source_request_id"] is None
        linked = await investigator.post(
            f"{link}/apply", json=sign(links, *investigator_key, counter=2)
        )
        assert linked.status_code == 200, linked.text
        assert "synthetic-private-marker" not in linked.text
        assert (await investigator.post(f"{premature}/options")).status_code == 409

        verify = await propose(5, "verify", source_event_id=str(evidence_id))
        review = await info(investigator, verify)
        assert review["proposal"]["source_request_id"] == request_id
        assert review["proposal"]["source_status"] == 200
        verified = await investigator.post(
            f"{verify}/apply", json=sign(review, *investigator_key, counter=3)
        )
        assert verified.status_code == 200, verified.text
        assert (await owner.get(case)).json()["status"] == "verified"
        close = await propose(6, "close")
        assert (await owner.post(f"{close}/options")).status_code == 403
        closure = await info(investigator, close)
        assert closure["proposal"]["source_event_id"] == str(evidence_id)
        closed = await investigator.post(
            f"{close}/apply", json=sign(closure, *investigator_key, counter=4)
        )
        assert closed.status_code == 200, closed.text
        assert (await owner.get(case)).json()["status"] == "closed"
        assert (await investigator.post(f"{close}/options")).status_code == 409

        timeline = await investigator.get(f"{case}/timeline")
        assert timeline.status_code == 200, timeline.text
        assert "synthetic-private-marker" not in timeline.text
        assert str(operator_id) not in timeline.text
        assert (await owner.get(f"{case}/timeline")).status_code == 403
        assert (await investigator.get(f"{CASES}/{uuid4()}/timeline")).status_code == 404
        items = timeline.json()["events"]
        assert [item["kind"] for item in items] == [
            "close",
            "verify",
            "evidence_link",
            "transitioned",
            "transitioned",
            "member_add",
            "created",
        ]
        assert items[1]["request_id"] == request_id
        assert items[1]["request_status"] == 200

        async with AsyncSessionLocal() as session:
            audit = await session.scalar(
                select(SupportCaseEvent).where(
                    SupportCaseEvent.case_id == UUID(case_id),
                    SupportCaseEvent.action == "timeline_read",
                )
            )
            assert audit is not None and audit.operator_id == operator_id
            key = UUID(closed.json()["id"])
            events = await session.scalars(
                select(SupportCaseActionEvent.event).where(SupportCaseActionEvent.action_id == key)
            )
            assert set(events) == {"requested", "applied"}
            with pytest.raises(DBAPIError, match="receipt are immutable"):
                async with session.begin_nested():
                    await session.execute(
                        update(SupportCaseAction)
                        .where(SupportCaseAction.id == key)
                        .values(case_revision=88)
                    )
            with pytest.raises(DBAPIError, match="append-only"):
                await session.execute(
                    update(SupportCaseActionEvent)
                    .where(SupportCaseActionEvent.action_id == key)
                    .values(event="requested")
                )


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_project_scope_requires_independent_review_and_updates_case_revision() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as reviewer, client() as other:
        owner_id = await case_operator(owner)
        reviewer_key = await login(reviewer, custodian=False)
        reviewer_id = reviewer_key[0]
        other_id = await case_operator(other)
        created = await owner.post(
            CASES,
            json={"external_ref": str(uuid4()), "severity": "high", "reason_code": "functional"},
        )
        assert created.status_code == 201, created.text
        case_id = UUID(created.json()["id"])
        root = f"{CASES}/{case_id}/actions"
        project_id = uuid4()
        project = {"kind": "project_add", "project_id": str(project_id)}
        revision = {"If-Match": '"1"'}
        assert (await owner.post(root, headers=revision, json=project)).status_code == 403

        async with AsyncSessionLocal() as db:
            db.add_all([
                Project(id=project_id, name="Private fixture project", code=project_id.hex[:12],
                        scope_of_work="Private scope", target_end_date=date(2030, 1, 1)),
                SupportCaseMember(case_id=case_id, operator_id=reviewer_id),
                SupportOperatorGrant(operator_id=reviewer_id, capability="cases.manage"),
                SupportOperatorGrant(operator_id=owner_id, capability="simulation.start"),
                SupportOperatorGrant(operator_id=other_id, capability="simulation.start"),
            ])
            await db.commit()

        invalid = await owner.post(root, headers=revision, json={"kind": "project_add"})
        assert invalid.status_code == 422
        assert (await other.post(root, headers=revision, json=project)).status_code == 404
        proposed = await owner.post(root, headers=revision, json=project)
        assert proposed.status_code == 201, proposed.text
        add = f"{root}/{proposed.json()['id']}"
        assert (await owner.post(f"{add}/options")).status_code == 403
        assert (await reviewer.post(f"{add}/options")).status_code == 404
        assert (await other.post(f"{add}/options")).status_code == 404
        async with AsyncSessionLocal() as db:
            assert await db.get(SupportCaseProject, (case_id, project_id)) is None
            db.add(SupportOperatorGrant(operator_id=reviewer_id, capability="simulation.start"))
            await db.commit()

        prepared = await reviewer.post(f"{add}/options")
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["proposal"]["project_id"] == str(project_id)
        assert "Private fixture project" not in prepared.text
        assert "Private scope" not in prepared.text
        applied = await reviewer.post(
            f"{add}/apply", json=sign(prepared.json(), *reviewer_key, counter=2)
        )
        assert applied.status_code == 200, applied.text
        assert (await owner.get(f"{CASES}/{case_id}")).json()["revision"] == 2
        assert (await owner.post(root, headers=revision, json=project)).status_code == 409
        async with AsyncSessionLocal() as db:
            assert await db.get(SupportCaseProject, (case_id, project_id)) is not None
            await db.execute(
                update(Project).where(Project.id == project_id).values(deleted_at=utc_now())
            )
            await db.commit()

        proposed = await owner.post(root, headers={"If-Match": '"2"'},
                                    json={**project, "kind": "project_remove"})
        assert proposed.status_code == 201, proposed.text
        remove = f"{root}/{proposed.json()['id']}"
        prepared = await reviewer.post(f"{remove}/options")
        assert prepared.status_code == 200, prepared.text
        applied = await reviewer.post(
            f"{remove}/apply", json=sign(prepared.json(), *reviewer_key, counter=3)
        )
        assert applied.status_code == 200, applied.text
        assert (await owner.get(f"{CASES}/{case_id}")).json()["revision"] == 3
        async with AsyncSessionLocal() as db:
            assert await db.get(SupportCaseProject, (case_id, project_id)) is None
            actions = await db.scalars(
                select(SupportCaseAction).where(SupportCaseAction.case_id == case_id)
            )
            applied_kinds = {
                item.kind for item in actions if item.applied_at and item.project_id == project_id
            }
            assert applied_kinds == {
                "project_add", "project_remove",
            }


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_cli_sealed_proof_is_session_bound_and_redeemed_once() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as reviewer, client() as browser:
        await case_operator(owner)
        reviewer_key = await login(reviewer)
        member = await login(browser, custodian=False)
        async with AsyncSessionLocal() as db:
            db.add(SupportOperatorGrant(operator_id=member[0], capability="cases.manage"))
            await db.commit()
        created = await owner.post(CASES, json={
            "external_ref": f"proof-{uuid4()}", "reason_code": "functional", "severity": "high",
        })
        case = f"{CASES}/{created.json()['id']}"
        proposal = await owner.post(
            f"{case}/actions", headers={"If-Match": '"1"'},
            json={"kind": "member_add", "member_id": str(member[0])},
        )
        path = f"{case}/actions/{proposal.json()['id']}"
        options = await reviewer.post(f"{path}/options")
        assert options.status_code == 200, options.text
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        code = "123456789abc"
        start = {
            "proof_id": options.json()["challenge_id"],
            "pairing_hash": sha256(code.encode()).hexdigest(), "encryption_key": encoded(public),
        }
        relay = f"{API}/auth/cli-proof"
        assert (await owner.post(f"{relay}/start", json=start)).status_code == 404
        opened = await reviewer.post(f"{relay}/start", json=start)
        assert opened.status_code == 200, opened.text
        reference = opened.json()["reference"]
        pair = {"reference": reference, "pairing_code": code}
        assert (await browser.post(f"{relay}/options", json={
            **pair, "pairing_code": "0" * 12,
        })).status_code == 404
        prepared = await browser.post(f"{relay}/options", json=pair)
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["operation"] == "member_add"
        assert prepared.json()["stage"] == "apply"
        assertion = sign(prepared.json(), *reviewer_key, counter=2)
        # Exercise the same wire format as Chrome. The database receives only ciphertext.
        aes = AESGCM.generate_key(bit_length=256)
        nonce = bytes(range(12))
        oaep = padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None,
        )
        encrypted = key.public_key().encrypt(aes, oaep) + nonce + AESGCM(aes).encrypt(
            nonce, json.dumps(assertion).encode(), reference.encode()
        )
        packet = {**pair, "sealed": encoded(encrypted)}
        received = await browser.post(f"{relay}/submit", json=packet)
        assert received.status_code == 204
        assert (await browser.post(f"{relay}/submit", json=packet)).status_code == 404
        selection = {"reference": reference}
        assert (await owner.post(f"{relay}/take", json=selection)).status_code == 404
        concurrently = await asyncio.gather(
            reviewer.post(f"{relay}/take", json=selection),
            reviewer.post(f"{relay}/take", json=selection),
        )
        assert sorted(result.status_code for result in concurrently) == [200, 404]
        recovered = next(result.json()["sealed"] for result in concurrently if result.is_success)
        assert recovered == packet["sealed"]
        assert assertion["credential"]["response"]["signature"] not in recovered
        proof = json.loads(AESGCM(key.decrypt(encrypted[:256], oaep)).decrypt(
            encrypted[256:268], encrypted[268:], reference.encode()
        ))
        applied = await reviewer.post(f"{path}/apply", json=proof)
        assert applied.status_code == 200, applied.text
        assert (await reviewer.post(f"{path}/apply", json=proof)).status_code == 409
        assert (await browser.get(case)).status_code == 200
        async with AsyncSessionLocal() as db:
            stored = await db.get(SupportCliProof, UUID(reference))
            assert stored and stored.taken_at and stored.sealed is None
