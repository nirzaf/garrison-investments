import asyncio
import csv
import hashlib
import io
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from app.api.v1.support import SESSION_COOKIE
from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.support_cases import (
    SupportCaseMember,
    SupportCaseRequest,
    SupportOperatorGrant,
)
from app.models.support_evidence_export import SupportEvidenceExport
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_cases import CASES
from tests.test_support_custody import login
from tests.test_support_identity import API, client, encoded, options, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


async def setup_export(owner: httpx.AsyncClient, reviewer: httpx.AsyncClient):
    requester = await login(owner)
    approver = await login(reviewer, custodian=False)
    async with AsyncSessionLocal() as db:
        for user in (requester, approver):
            db.add(SupportOperatorGrant(operator_id=user[0], capability="logs.runtime"))
            db.add(SupportOperatorGrant(operator_id=user[0], capability="logs.export"))
        db.add(SupportOperatorGrant(operator_id=requester[0], capability="cases.manage"))
        await db.commit()
    case_response = await owner.post(
        CASES,
        json={
            "external_ref": f"export-{uuid4()}",
            "severity": "high",
            "reason_code": "access",
        },
    )
    assert case_response.status_code == 201
    case = UUID(case_response.json()["id"])
    source, now = uuid4().hex, utc_now()
    async with AsyncSessionLocal() as db:
        db.add(SupportCaseMember(case_id=case, operator_id=approver[0]))
        db.add(SupportCaseRequest(case_id=case, request_id=source))
        for index in range(2):
            db.add(
                ActivityLog(
                    id=uuid4(),
                    request_id=source,
                    action="http.request",
                    entity_type="request",
                    http_method="=1+2",
                    endpoint="/fixture?secret=private",
                    comments="private-export-marker",
                    status_code=200,
                    created_at=now - timedelta(seconds=10 + index),
                )
            )
        await db.commit()
    filters = {
        "request_id": source,
        "started_at": (now - timedelta(days=2)).isoformat(),
        "ended_at": now.isoformat(),
        "status_code": 200,
        "limit": 1,
    }
    return requester, approver, case, filters


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_evidence_export_is_independently_reviewed_bounded_and_consumed_once() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as reviewer, client() as other_session:
        requester, approver, case, filters = await setup_export(owner, reviewer)
        root = f"{CASES}/{case}/exports"
        payload = {"filters": filters, "reason": "incident_review"}
        for invalid in (
            {**filters, "started_at": (utc_now() - timedelta(days=8)).isoformat()},
            {**filters, "limit": 10_001},
            {**filters, "request_id": uuid4().hex},
        ):
            result = await owner.post(root, json={**payload, "filters": invalid})
            assert result.status_code == (
                404 if invalid["request_id"] != filters["request_id"] else 422
            )
        created = await owner.post(root, json=payload)
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["row_count"] == 1 and manifest["truncated"] is True
        path = f"{root}/{manifest['id']}"
        assert (await owner.post(path + "/review/options")).status_code == 403
        assert (await owner.post(path + "/download/options")).status_code == 409
        ready = await reviewer.post(path + "/review/options")
        assert ready.status_code == 200 and ready.json()["export"] == manifest
        public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
        pairing = "839712345acd"
        relay = f"{API}/auth/cli-proof"
        started = await reviewer.post(
            f"{relay}/start",
            json={
                "proof_id": ready.json()["challenge_id"],
                "pairing_hash": hashlib.sha256(pairing.encode()).hexdigest(),
                "encryption_key": encoded(
                    public.public_bytes(
                        serialization.Encoding.DER,
                        serialization.PublicFormat.SubjectPublicKeyInfo,
                    )
                ),
            },
        )
        assert started.status_code == 200
        paired = await other_session.post(
            f"{relay}/options",
            json={
                "reference": started.json()["reference"],
                "pairing_code": pairing,
            },
        )
        assert paired.status_code == 200
        assert (
            paired.json()["stage"] == "review" and paired.json()["operation"] == "evidence_export"
        )
        proof = sign(ready.json(), *approver, counter=2)
        forged = {**proof, "expected_sha256": "0" * 64}
        assert (await reviewer.post(path + "/review", json=forged)).status_code == 409
        approved = await reviewer.post(
            path + "/review", json={**proof, "expected_sha256": manifest["sha256"]}
        )
        assert approved.status_code == 200 and approved.json()["approved_at"]

        assert (
            await other_session.post(
                "/api/v1/support/auth/verify",
                json=sign(await options(other_session, requester[0]), *requester, counter=2),
            )
        ).status_code == 200
        assert (await other_session.post(path + "/download/options")).status_code == 403
        assert other_session.cookies[SESSION_COOKIE] != owner.cookies[SESSION_COOKIE]
        prepared = await owner.post(path + "/download/options")
        assert prepared.status_code == 200
        request = {
            **sign(prepared.json(), *requester, counter=3),
            "expected_sha256": manifest["sha256"],
        }
        results = await asyncio.gather(
            *(owner.post(path + "/download", json=request) for _ in range(2))
        )
        assert sorted(result.status_code for result in results) == [200, 409]
        downloaded = next(result for result in results if result.is_success)
        assert downloaded.headers["cache-control"] == "no-store"
        assert downloaded.headers["x-support-export-truncated"] == "true"
        assert hashlib.sha256(downloaded.content).hexdigest() == manifest["sha256"]
        assert (
            'attachment; filename="support-evidence-' in downloaded.headers["content-disposition"]
        )
        batch = list(csv.DictReader(io.StringIO(downloaded.text)))
        assert len(batch) == 2
        assert batch[0]["record_type"] == "manifest" and batch[0]["truncated"] == "true"
        assert batch[1]["record_type"] == "event" and batch[1]["method"] == ""
        assert not any(s in downloaded.text for s in ("private", "=1+2", "/fixture"))
        async with AsyncSessionLocal() as db:
            record = await db.get(SupportEvidenceExport, UUID(manifest["id"]))
            assert record and record.downloaded_at and record.download_request_id
            with pytest.raises(DBAPIError):
                await db.execute(
                    update(SupportEvidenceExport)
                    .where(SupportEvidenceExport.id == record.id)
                    .values(sha256="f" * 64)
                )
            await db.rollback()


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_evidence_export_rejects_new_rows_after_review() -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as reviewer:
        requester, approver, case, filters = await setup_export(owner, reviewer)
        root = f"{CASES}/{case}/exports"
        proposed = await owner.post(root, json={"filters": filters, "reason": "audit_review"})
        assert proposed.status_code == 201
        receipt = proposed.json()
        path = f"{root}/{receipt['id']}"
        ready = await reviewer.post(path + "/review/options")
        signed = sign(ready.json(), *approver, counter=2)
        approved = await reviewer.post(
            path + "/review", json={**signed, "expected_sha256": receipt["sha256"]}
        )
        assert approved.status_code == 200
        prepared = await owner.post(path + "/download/options")
        assert prepared.status_code == 200
        async with AsyncSessionLocal() as db:
            record = await db.scalar(
                select(SupportEvidenceExport).where(SupportEvidenceExport.id == UUID(receipt["id"]))
            )
            assert record is not None
            db.add(
                ActivityLog(
                    id=uuid4(),
                    request_id=record.source_request_id,
                    action="http.request",
                    entity_type="request",
                    http_method="GET",
                    status_code=200,
                    created_at=record.ended_at - timedelta(seconds=1),
                )
            )
            await db.commit()
        proof = sign(prepared.json(), *requester, counter=2)
        denied = await owner.post(
            path + "/download", json={**proof, "expected_sha256": receipt["sha256"]}
        )
        assert denied.status_code == 409 and "text/csv" not in denied.headers["content-type"]
        async with AsyncSessionLocal() as db:
            record = await db.get(SupportEvidenceExport, UUID(receipt["id"]))
            assert record and record.approved_at and record.downloaded_at is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
async def test_single_owner_export_records_own_confirmation_and_rejects_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await skip_if_database_unavailable()
    async with client() as owner, client() as other:
        requester, _, case, filters = await setup_export(owner, other)

        async def is_owner(_identity, actor_id):
            return actor_id == requester[0]

        monkeypatch.setattr(
            "app.services.support_identity.SupportIdentity.is_single_owner", is_owner
        )
        root = f"{CASES}/{case}/exports"
        created = await owner.post(root, json={"filters": filters, "reason": "incident_review"})
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["authorization_mode"] == "single_owner"
        path = f"{root}/{manifest['id']}"
        assert (await other.post(path + "/review/options")).status_code == 403
        assert (await owner.post(path + "/download/options")).status_code == 409
        ready = await owner.post(path + "/review/options")
        assert ready.status_code == 200, ready.text
        proof = {**sign(ready.json(), *requester, counter=2), "expected_sha256": manifest["sha256"]}
        results = await asyncio.gather(
            *(owner.post(path + "/review", json=proof) for _ in range(2))
        )
        assert sorted(result.status_code for result in results) == [200, 409]
        download = await owner.post(path + "/download/options")
        assert download.status_code == 200, download.text
        response = await owner.post(
            path + "/download",
            json={
                **sign(download.json(), *requester, counter=3),
                "expected_sha256": manifest["sha256"],
            },
        )
        assert response.status_code == 200, response.text
        assert hashlib.sha256(response.content).hexdigest() == manifest["sha256"]
        async with AsyncSessionLocal() as db:
            record = await db.get(SupportEvidenceExport, UUID(manifest["id"]))
            assert record and record.approved_at and record.downloaded_at
            assert record.reviewer_id is None and record.reviewer_epoch is None
            with pytest.raises(DBAPIError):
                await db.execute(
                    update(SupportEvidenceExport)
                    .where(SupportEvidenceExport.id == record.id)
                    .values(authorization_mode="paired")
                )
            await db.rollback()
