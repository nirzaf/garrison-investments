from io import BytesIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.document import DocumentVersion
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.storage_service import minio_client
from tests.concurrency_helpers import race_sessions, status_counts
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    login_for_token,
    setup_project_team,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def frontend_base_url(monkeypatch):
    monkeypatch.setattr(
        "app.utils.links.get_settings",
        lambda: SimpleNamespace(normalized_frontend_base_url="https://portal.example.com"),
    )


def pdf_bytes(label: str = "doc") -> bytes:
    return f"%PDF-1.4\n1 0 obj<<>>endobj\n% {label}\n%%EOF".encode()


async def test_document_upload_approval_versioning_and_superseded_download() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        approver_email, approver_password = await create_user("managing_director")
        approver_token = await login_for_token(client, approver_email, approver_password)
        approver_headers = {"Authorization": f"Bearer {approver_token}"}
        uploader_headers = {"Authorization": f"Bearer {setup['op_token']}"}
        upload_response = await client.post(
            "/api/v1/documents",
            data={
                "title": "WIR Zone A",
                "document_type": "wir",
                "project_id": setup["project_id"],
            },
            files={"file": ("wir.pdf", pdf_bytes("v1"), "application/pdf")},
            headers=uploader_headers,
        )

        assert upload_response.status_code == 201
        document = upload_response.json()
        assert document["status"] == "pending_approval"
        first_version = document["versions"][0]

        documents = [document]
        for title in ("WIR Zone B", "WIR Zone C"):
            uploaded = await client.post(
                "/api/v1/documents",
                data={"title": title, "document_type": "wir", "project_id": setup["project_id"]},
                files={"file": ("wir.pdf", pdf_bytes(title), "application/pdf")},
                headers=uploader_headers,
            )
            assert uploaded.status_code == 201
            documents.append(uploaded.json())
        for item in documents:
            classified = await client.patch(
                f"/api/v1/documents/{item['id']}/classification",
                json={
                    "classification": "operational",
                    "expected_classification": item["classification"],
                    "expected_updated_at": item["updated_at"],
                    "reason": "Verified WIR evidence.",
                },
                headers=approver_headers,
            )
            assert classified.status_code == 200, classified.text
        for offset, expected_title in enumerate(("WIR Zone C", "WIR Zone B", "WIR Zone A")):
            page = await client.get(
                "/api/v1/documents",
                params={"project_id": setup["project_id"], "limit": 1, "offset": offset},
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
            assert page.status_code == 200
            assert page.json()["total"] == 3
            assert [item["title"] for item in page.json()["items"]] == [expected_title]

        engineer_notifications = await client.get(
            "/api/v1/notifications",
            headers=uploader_headers,
        )
        assert any(
            item["title"] == "Document uploaded"
            and item["body"]
            == "WIR Zone A is pending approval.\n\n"
            "Open document: https://portal.example.com/documents?documentId="
            f"{document['id']}&versionId={first_version['id']}"
            for item in engineer_notifications.json()["items"]
        )

        approve_response = await client.post(
            f"/api/v1/documents/{document['id']}/versions/{first_version['id']}/approve",
            json={"comments": "Approved"},
            headers=approver_headers,
        )

        assert approve_response.status_code == 200
        active_document = approve_response.json()
        assert active_document["status"] == "active"
        assert active_document["active_version"] == 1

        version_response = await client.post(
            f"/api/v1/documents/{document['id']}/versions",
            data={"classification": "operational"},
            files={"file": ("wir-rev2.pdf", pdf_bytes("v2"), "application/pdf")},
            headers=uploader_headers,
        )
        second_version = max(version_response.json()["versions"], key=lambda item: item["version"])
        second_approve_response = await client.post(
            f"/api/v1/documents/{document['id']}/versions/{second_version['id']}/approve",
            json={"comments": "Revision approved"},
            headers=approver_headers,
        )

        assert second_approve_response.status_code == 200
        revised = second_approve_response.json()
        assert revised["active_version"] == 2
        assert revised["versions"][0]["status"] == "superseded"

        engineer_notifications_after_approval = await client.get(
            "/api/v1/notifications",
            headers=uploader_headers,
        )
        assert any(
            item["title"] == "Document version approved"
            and item["body"]
            == "WIR Zone A version 2 is now active.\n\n"
            "Open document: https://portal.example.com/documents?documentId="
            f"{document['id']}&versionId={second_version['id']}"
            for item in engineer_notifications_after_approval.json()["items"]
        )

        old_download = await client.get(
            f"/api/v1/documents/{document['id']}/download",
            params={"version_id": first_version["id"]},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert old_download.status_code == 200
        assert old_download.json()["superseded_warning"] is True

        supervisor_download = await client.get(
            f"/api/v1/documents/{document['id']}/download",
            headers={"Authorization": f"Bearer {setup['supervisor_token']}"},
        )
        assert supervisor_download.status_code == 200

        blocked_supervisor_upload = await client.post(
            "/api/v1/documents",
            data={
                "title": "Supervisor Read Only Upload",
                "document_type": "wir",
                "project_id": setup["project_id"],
            },
            files={"file": ("blocked.pdf", pdf_bytes("blocked"), "application/pdf")},
            headers={"Authorization": f"Bearer {setup['supervisor_token']}"},
        )
        assert blocked_supervisor_upload.status_code == 403


async def test_document_search_finds_uploaded_metadata() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        uploaded = await client.post(
            "/api/v1/documents",
            data={
                "title": "Delivery Note Concrete",
                "document_type": "delivery_note",
                "project_id": setup["project_id"],
            },
            files={"file": ("delivery.pdf", pdf_bytes("delivery"), "application/pdf")},
            headers={"Authorization": f"Bearer {setup['op_token']}"},
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.headers["cache-control"] == "no-store"
        reviewer_email, reviewer_password = await create_user("managing_director")
        reviewer_token = await login_for_token(client, reviewer_email, reviewer_password)
        classified = await client.patch(
            f"/api/v1/documents/{uploaded.json()['id']}/classification",
            json={
                "classification": "operational",
                "expected_classification": uploaded.json()["classification"],
                "expected_updated_at": uploaded.json()["updated_at"],
                "reason": "Verified delivery note.",
            },
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert classified.status_code == 200, classified.text

        response = await client.get(
            "/api/v1/documents",
            params={"search": "concrete"},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert response.status_code == 200
        assert response.json()["total"] >= 1


async def test_document_replacements_serialize_and_keep_active_version() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        approver_email, approver_password = await create_user("managing_director")
        approver_token = await login_for_token(client, approver_email, approver_password)
        uploader = {"Authorization": f"Bearer {team['op_token']}"}
        approver = {"Authorization": f"Bearer {approver_token}"}
        response = await client.post(
            "/api/v1/documents",
            data={
                "title": "Race plan",
                "document_type": "drawing",
                "project_id": team["project_id"],
            },
            files={"file": ("v1.pdf", pdf_bytes("v1"), "application/pdf")},
            headers=uploader,
        )
        assert response.status_code == 201
        document = response.json()
        path = f"/api/v1/documents/{document['id']}"
        first = document["versions"][0]
        response = await client.post(
            f"{path}/versions/{first['id']}/approve", json={}, headers=approver
        )
        assert response.status_code == 200

        document_id = UUID(document["id"])
        identity = (await client.get("/api/v1/auth/me", headers=uploader)).json()

        def replace(label: str):
            async def run(session: AsyncSession) -> int:
                actor = await session.get_one(User, UUID(identity["id"]))
                await DocumentService(session).upload_version(
                    document_id,
                    UploadFile(BytesIO(pdf_bytes(label)), filename=f"{label}.pdf"),
                    actor,
                    f"document-{label}",
                )
                return 200

            return run

        results = await race_sessions(replace("revision-a"), replace("revision-b"))
        assert status_counts(results) == {200: 2}

        listed = await client.get(path, headers=uploader)
        assert listed.status_code == 200
        assert listed.json()["active_version"] == 1
        assert [version["version"] for version in listed.json()["versions"]] == [1, 2, 3]
        assert [version["status"] for version in listed.json()["versions"]] == [
            "active",
            "pending_approval",
            "pending_approval",
        ]
        assert (await client.get(f"{path}/download", headers=uploader)).status_code == 200

        replay = await client.post(
            f"{path}/versions",
            files={"file": ("revision-a.pdf", pdf_bytes("revision-a"), "application/pdf")},
            headers={**uploader, "Idempotency-Key": "document-revision-a"},
        )
        assert replay.status_code == 200
        assert len(replay.json()["versions"]) == 3

        selected = listed.json()["versions"][2]
        forbidden = await client.post(
            f"{path}/versions/{selected['id']}/approve", json={}, headers=uploader
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["error_code"] == "DOCUMENT_SELF_APPROVAL_FORBIDDEN"
        approved = await client.post(
            f"{path}/versions/{selected['id']}/approve", json={}, headers=approver
        )
        assert approved.status_code == 200
        assert approved.json()["active_version"] == 3
        assert approved.json()["versions"][0]["status"] == "superseded"


async def test_replacement_failure_discards_only_the_new_object(monkeypatch) -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        approver_email, approver_password = await create_user("managing_director")
        approver_token = await login_for_token(client, approver_email, approver_password)
        actor = {"Authorization": f"Bearer {team['op_token']}"}
        approver = {"Authorization": f"Bearer {approver_token}"}
        response = await client.post(
            "/api/v1/documents",
            data={
                "title": "Failure plan",
                "document_type": "drawing",
                "project_id": team["project_id"],
            },
            files={"file": ("v1.pdf", pdf_bytes("v1"), "application/pdf")},
            headers=actor,
        )
        assert response.status_code == 201
        document = response.json()
        path = f"/api/v1/documents/{document['id']}"
        version = document["versions"][0]
        approved = await client.post(
            f"{path}/versions/{version['id']}/approve", json={}, headers=approver
        )
        assert approved.status_code == 200

        async def fail_record(*args, **kwargs):
            raise RuntimeError("synthetic persistence failure")

        monkeypatch.setattr(DocumentRepository, "add_version", fail_record)
        failed = await client.post(
            f"{path}/versions",
            files={"file": ("v2.pdf", pdf_bytes("v2"), "application/pdf")},
            headers=actor,
        )
        assert failed.status_code == 503
        assert failed.json()["error_code"] == "DOCUMENT_VERSION_SAVE_FAILED"
        current = await client.get(path, headers=actor)
        assert current.json()["active_version"] == 1
        assert len(current.json()["versions"]) == 1
        settings = get_settings()
        stored = list(
            minio_client(settings).list_objects(
                settings.minio_bucket, prefix=f"documents/{document['id']}/", recursive=True
            )
        )
        assert [item.object_name for item in stored] == [version["storage_path"]]


async def test_unclassified_documents_are_restricted_until_independent_review() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        uploader = {"Authorization": f"Bearer {team['op_token']}"}
        uploaded = await client.post(
            "/api/v1/documents",
            data={
                "title": "Restricted Site Evidence",
                "document_type": "wir",
                "project_id": team["project_id"],
            },
            files={"file": ("restricted.pdf", pdf_bytes(), "application/pdf")},
            headers=uploader,
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.headers["cache-control"] == "no-store"
        document = uploaded.json()
        assert document["classification"] == "unclassified"

        manager = {"Authorization": f"Bearer {team['supervisor_token']}"}
        for path in (
            f"/api/v1/documents/{document['id']}",
            f"/api/v1/documents/{document['id']}/download",
            f"/api/v1/documents/{document['id']}/versions",
        ):
            denied = await client.get(path, headers=manager)
            assert denied.status_code == 404, (path, denied.text)
        hidden = await client.get("/api/v1/documents", headers=manager)
        assert hidden.headers["cache-control"] == "no-store"
        assert document["id"] not in {item["id"] for item in hidden.json()["items"]}

        denied_review = await client.patch(
            f"/api/v1/documents/{document['id']}/classification",
            json={
                "classification": "operational",
                "expected_classification": document["classification"],
                "expected_updated_at": document["updated_at"],
                "reason": "Reviewed",
            },
            headers=manager,
        )
        assert denied_review.status_code == 403

        reviewer_email, reviewer_password = await create_user("managing_director")
        reviewer_token = await login_for_token(client, reviewer_email, reviewer_password)
        reviewer = {"Authorization": f"Bearer {reviewer_token}"}
        reviewed = await client.patch(
            f"/api/v1/documents/{document['id']}/classification",
            json={
                "classification": "operational",
                "expected_classification": document["classification"],
                "expected_updated_at": document["updated_at"],
                "reason": "Verified site evidence.",
            },
            headers=reviewer,
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["classification"] == "operational"
        manager_read = await client.get(
            f"/api/v1/documents/{document['id']}", headers=manager
        )
        assert manager_read.status_code == 200
        assert manager_read.headers["cache-control"] == "no-store"

        duplicate = await client.patch(
            f"/api/v1/documents/{document['id']}/classification",
            json={
                "classification": "operational",
                "expected_classification": reviewed.json()["classification"],
                "expected_updated_at": reviewed.json()["updated_at"],
                "reason": "Second review.",
            },
            headers=reviewer,
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error_code"] == "EVIDENCE_CLASSIFICATION_ALREADY_REVIEWED"

        invoice = await client.post(
            "/api/v1/documents",
            data={
                "title": "Restricted Invoice Evidence",
                "document_type": "invoice",
                "project_id": team["project_id"],
            },
            files={"file": ("invoice.pdf", pdf_bytes("invoice"), "application/pdf")},
            headers=uploader,
        )
        assert invoice.status_code == 201
        assert invoice.json()["classification"] == "financial"
        manager_invoice = await client.get(
            f"/api/v1/documents/{invoice.json()['id']}",
            headers={"Authorization": f"Bearer {team['supervisor_token']}"},
        )
        assert manager_invoice.status_code == 404


async def test_restricted_document_version_keeps_parent_fail_closed() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        uploader = {"Authorization": f"Bearer {team['op_token']}"}
        uploaded = await client.post(
            "/api/v1/documents",
            data={
                "title": "Mixed Classification Version",
                "document_type": "wir",
                "project_id": team["project_id"],
            },
            files={"file": ("mixed.pdf", pdf_bytes(), "application/pdf")},
            headers=uploader,
        )
        assert uploaded.status_code == 201, uploaded.text
        document = uploaded.json()
        version_id = UUID(document["versions"][0]["id"])
        async with AsyncSessionLocal.begin() as session:
            version = await session.get(DocumentVersion, version_id)
            assert version is not None
            version.classification = "financial"

        supervisor = {"Authorization": f"Bearer {team['supervisor_token']}"}
        for path in (
            f"/api/v1/documents/{document['id']}",
            f"/api/v1/documents/{document['id']}/versions",
            f"/api/v1/documents/{document['id']}/download",
        ):
            denied = await client.get(path, headers=supervisor)
            assert denied.status_code == 404, (path, denied.text)
        listed = await client.get("/api/v1/documents", headers=supervisor)
        assert document["id"] not in {item["id"] for item in listed.json()["items"]}

        reviewer_email, reviewer_password = await create_user("managing_director")
        reviewer_token = await login_for_token(client, reviewer_email, reviewer_password)
        stale_downgrade = await client.patch(
            f"/api/v1/documents/{document['id']}/classification",
            json={
                "classification": "operational",
                "expected_classification": "unclassified",
                "expected_updated_at": document["updated_at"],
                "reason": "Review version classifications.",
            },
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert stale_downgrade.status_code == 422, stale_downgrade.text
        assert stale_downgrade.json()["error_code"] == "EVIDENCE_CLASSIFICATION_INVALID"
        financial_read = await client.get(
            f"/api/v1/documents/{document['id']}",
            headers={"Authorization": f"Bearer {reviewer_token}"},
        )
        assert financial_read.status_code == 200, financial_read.text
        assert financial_read.json()["versions"][0]["classification"] == "financial"

        operational_upload = await client.post(
            "/api/v1/documents",
            data={
                "title": "Version Restriction Filter",
                "document_type": "wir",
                "project_id": team["project_id"],
                "classification": "operational",
            },
            files={"file": ("filter.pdf", pdf_bytes(), "application/pdf")},
            headers=uploader,
        )
        assert operational_upload.status_code == 201, operational_upload.text
        operational_document = operational_upload.json()
        operational_version_id = UUID(operational_document["versions"][0]["id"])
        async with AsyncSessionLocal.begin() as session:
            version = await session.get(DocumentVersion, operational_version_id)
            assert version is not None
            version.classification = "financial"
        direct_denial = await client.get(
            f"/api/v1/documents/{operational_document['id']}", headers=supervisor
        )
        assert direct_denial.status_code == 404, direct_denial.text
        listed = await client.get("/api/v1/documents", headers=supervisor)
        assert operational_document["id"] not in {
            item["id"] for item in listed.json()["items"]
        }
