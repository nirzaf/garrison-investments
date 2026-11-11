from types import SimpleNamespace

import pytest

from app.database import engine
from tests.test_daily_reports import (
    create_test_client,
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
        upload_response = await client.post(
            "/api/v1/documents",
            data={
                "title": "WIR Zone A",
                "document_type": "wir",
                "project_id": setup["project_id"],
            },
            files={"file": ("wir.pdf", pdf_bytes("v1"), "application/pdf")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert upload_response.status_code == 201
        document = upload_response.json()
        assert document["status"] == "pending_approval"
        first_version = document["versions"][0]

        engineer_notifications = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
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
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert approve_response.status_code == 200
        active_document = approve_response.json()
        assert active_document["status"] == "active"
        assert active_document["active_version"] == 1

        version_response = await client.post(
            f"/api/v1/documents/{document['id']}/versions",
            files={"file": ("wir-rev2.pdf", pdf_bytes("v2"), "application/pdf")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        second_version = max(version_response.json()["versions"], key=lambda item: item["version"])
        second_approve_response = await client.post(
            f"/api/v1/documents/{document['id']}/versions/{second_version['id']}/approve",
            json={"comments": "Revision approved"},
            headers={"Authorization": f"Bearer {setup['manager_token']}"},
        )

        assert second_approve_response.status_code == 200
        revised = second_approve_response.json()
        assert revised["active_version"] == 2
        assert revised["versions"][0]["status"] == "superseded"

        engineer_notifications_after_approval = await client.get(
            "/api/v1/notifications",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
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
        await client.post(
            "/api/v1/documents",
            data={
                "title": "Delivery Note Concrete",
                "document_type": "delivery_note",
                "project_id": setup["project_id"],
            },
            files={"file": ("delivery.pdf", pdf_bytes("delivery"), "application/pdf")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        response = await client.get(
            "/api/v1/documents",
            params={"search": "concrete"},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert response.status_code == 200
        assert response.json()["total"] >= 1
