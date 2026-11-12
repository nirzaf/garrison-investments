from datetime import timedelta
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.activity_log import ActivityLog
from app.models.user import User
from app.services.photo_service import PhotoService
from app.services.storage_service import minio_client
from tests.concurrency_helpers import error_codes, race_sessions, status_counts
from tests.test_daily_reports import (
    business_today,
    create_test_client,
    create_user,
    login_for_token,
    report_payload,
    setup_project_team,
    skip_if_database_unavailable,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (20, 20), color=(80, 120, 160)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_photo_upload_download_url_and_delete_lock() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        upload_response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert upload_response.status_code == 201
        photo = upload_response.json()[0]
        assert photo["thumbnail_path"]

        recent_response = await client.get(
            "/api/v1/photos",
            params={"kind": "photo"},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        entity_response = await client.get(
            "/api/v1/photos",
            params={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert recent_response.status_code == 200
        assert recent_response.json()["total"] >= 1
        assert entity_response.status_code == 200
        assert entity_response.json()["items"][0]["id"] == photo["id"]

        url_response = await client.get(
            f"/api/v1/photos/{photo['id']}/thumbnail",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert url_response.status_code == 200
        assert "url" in url_response.json()

        await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        delete_response = await client.delete(
            f"/api/v1/photos/{photo['id']}",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert delete_response.status_code == 409


async def test_blocked_file_type_is_rejected() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        setup = await setup_project_team(client)
        report = (
            await client.post(
                "/api/v1/reports",
                json=report_payload(setup["project_id"], setup["supervisor_update_id"]),
                headers={"Authorization": f"Bearer {setup['engineer_token']}"},
            )
        ).json()
        response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "attachment"},
            files={"files": ("run.sh", b"#!/bin/sh\necho bad", "text/x-shellscript")},
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert response.status_code == 422


async def test_photo_quota_serializes_upload_and_recovery() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        admin_email, admin_password = await create_user("admin")
        admin_token = await login_for_token(client, admin_email, admin_password)
        admin = {"Authorization": f"Bearer {admin_token}"}
        report_response = await client.post(
            "/api/v1/reports",
            json=report_payload(team["project_id"], team["supervisor_update_id"]),
            headers=engineer,
        )
        assert report_response.status_code == 201
        report = report_response.json()
        owner = {"entity_type": "daily_report", "entity_id": report["id"]}
        upload = await client.post(
            "/api/v1/photos/upload",
            data={**owner, "kind": "photo"},
            files=[("files", (f"site{i}.jpg", jpeg_bytes(), "image/jpeg")) for i in range(5)],
            headers=engineer,
        )
        assert upload.status_code == 201
        first, second, *_ = upload.json()
        first_id, second_id = UUID(first["id"]), UUID(second["id"])
        assert (
            await client.delete(f"/api/v1/photos/{first_id}", headers=engineer)
        ).status_code == 204

        async def upload_one(session: AsyncSession) -> int:
            actor = await session.get_one(User, UUID(report["engineer_id"]))
            await PhotoService(session).upload(
                file=UploadFile(BytesIO(jpeg_bytes()), filename="race.jpg"),
                entity_type="daily_report",
                entity_id=UUID(report["id"]),
                kind="photo",
                caption=None,
                actor=actor,
            )
            return 201

        results = await race_sessions(upload_one, upload_one)
        assert status_counts(results) == {201: 1, 409: 1}
        assert error_codes(results) == ["REPORT_PHOTO_LIMIT_REACHED"]

        hidden_link = await client.get(f"/api/v1/photos/{first_id}/download", headers=engineer)
        assert hidden_link.status_code == 404
        denied = await client.get("/api/v1/photos", params={"deleted": True}, headers=engineer)
        assert denied.status_code == 403
        denied = await client.post(f"/api/v1/photos/{first_id}/recover", headers=engineer)
        assert denied.status_code == 403
        deleted = await client.get(
            "/api/v1/photos", params={**owner, "deleted": True}, headers=admin
        )
        assert deleted.status_code == 200
        assert deleted.json()["items"][0]["recoverable_until"]
        assert deleted.json()["items"][0]["id"] == str(first_id)
        full = await client.post(f"/api/v1/photos/{first_id}/recover", headers=admin)
        assert full.status_code == 409
        assert full.json()["error_code"] == "REPORT_PHOTO_LIMIT_REACHED"

        assert (
            await client.delete(f"/api/v1/photos/{second_id}", headers=engineer)
        ).status_code == 204
        admin_me = await client.get("/api/v1/auth/me", headers=admin)

        async def recover_one(session: AsyncSession) -> int:
            actor = await session.get_one(User, UUID(admin_me.json()["id"]))
            await PhotoService(session).recover(first_id, actor)
            return 200

        results = await race_sessions(upload_one, recover_one)
        counts = status_counts(results)
        assert counts in ({201: 1, 409: 1}, {200: 1, 409: 1})
        assert error_codes(results) == ["REPORT_PHOTO_LIMIT_REACHED"]
        listing = await client.get(
            "/api/v1/photos", params={**owner, "kind": "photo"}, headers=engineer
        )
        assert listing.json()["total"] == 5
        assert all(photo["can_delete"] for photo in listing.json()["items"])

        document = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF"
        upload = await client.post(
            "/api/v1/photos/upload",
            data={**owner, "kind": "photo"},
            files={"files": ("signature-only.bin", document, "application/octet-stream")},
            headers=engineer,
        )
        assert upload.status_code == 201
        assert upload.json()[0]["kind"] == "attachment"


async def test_supervisor_photo_quota_and_final_state_are_checked() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        actor = {"Authorization": f"Bearer {team['supervisor_token']}"}
        response = await client.post(
            "/api/v1/supervisor-updates",
            json={
                "project_id": team["project_id"],
                "update_date": str(business_today() - timedelta(days=1)),
                "day_type": "weekday",
                "work_location": "Quota site",
                "attendance_count": 1,
                "overtime_hours": "0",
                "progress_notes": "Test quota.",
                "required_notes": "No incidents.",
            },
            headers=actor,
        )
        assert response.status_code == 201
        update_id = response.json()["id"]
        data = {"entity_type": "supervisor_update", "entity_id": update_id, "kind": "photo"}
        file = ("site.heic", b"\x00\x00\x00\x18ftypheic" + b"\x00" * 12, "image/heic")
        response = await client.post(
            "/api/v1/photos/upload",
            data=data,
            files=[("files", file)] * 5,
            headers={**actor, "Idempotency-Key": "supervisor-quota"},
        )
        assert response.status_code == 201
        assert all(
            photo["mime_type"] == "image/heic"
            and photo["thumbnail_path"] is None
            and photo["compressed_path"] is None
            for photo in response.json()
        )
        blocked = await client.post(
            "/api/v1/photos/upload", data=data, files={"files": file}, headers=actor
        )
        assert blocked.status_code == 409
        assert blocked.json()["error_code"] == "REPORT_PHOTO_LIMIT_REACHED"
        repeated = await client.post(
            "/api/v1/photos/upload",
            data=data,
            files=[("files", file)] * 5,
            headers={**actor, "Idempotency-Key": "supervisor-quota"},
        )
        assert repeated.json() == response.json()

        submitted = await client.post(
            f"/api/v1/supervisor-updates/{update_id}/submit", headers=actor
        )
        assert submitted.status_code == 200
        upload = await client.post(
            "/api/v1/photos/upload",
            data={**data, "kind": "attachment"},
            files={"files": ("draft.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            headers=actor,
        )
        assert upload.status_code == 409
        assert upload.json()["error_code"] == "PHOTO_UPLOAD_LOCKED"


async def test_admin_reason_and_stored_bytes_are_required_for_finalized_evidence() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        admin_email, admin_password = await create_user("admin")
        admin_token = await login_for_token(client, admin_email, admin_password)
        admin = {"Authorization": f"Bearer {admin_token}"}
        report_response = await client.post(
            "/api/v1/reports",
            json=report_payload(team["project_id"], team["supervisor_update_id"]),
            headers=engineer,
        )
        assert report_response.status_code == 201
        report_id = report_response.json()["id"]
        upload = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report_id, "kind": "photo"},
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers=engineer,
        )
        assert upload.status_code == 201
        photo = upload.json()[0]
        photo_path = f"/api/v1/photos/{photo['id']}"
        submitted = await client.post(f"/api/v1/reports/{report_id}/submit", headers=engineer)
        assert submitted.status_code == 200

        no_reason = await client.delete(photo_path, headers=admin)
        assert no_reason.status_code == 422
        assert no_reason.json()["error_code"] == "PHOTO_CHANGE_REASON_REQUIRED"
        removal = await client.request(
            "DELETE",
            photo_path,
            json={"reason": "Synthetic evidence reconciliation."},
            headers=admin,
        )
        assert removal.status_code == 204

        no_reason = await client.post(f"{photo_path}/recover", headers=admin)
        assert no_reason.status_code == 422
        assert no_reason.json()["error_code"] == "PHOTO_CHANGE_REASON_REQUIRED"
        payload = {"reason": "Synthetic evidence confirmed."}
        recovered = await client.post(f"{photo_path}/recover", json=payload, headers=admin)
        assert recovered.status_code == 200
        async with AsyncSessionLocal() as session:
            actions = set(
                (
                    await session.scalars(
                        select(ActivityLog.comments).where(
                            ActivityLog.entity_id == UUID(report_id),
                            ActivityLog.action.in_(("photos.deleted", "photos.recovered")),
                        )
                    )
                ).all()
            )
            assert actions == {
                "Synthetic evidence reconciliation.",
                "Synthetic evidence confirmed.",
            }

        deleted = await client.request("DELETE", photo_path, json=payload, headers=admin)
        assert deleted.status_code == 204
        settings = get_settings()
        minio_client(settings).remove_object(settings.minio_bucket, photo["thumbnail_path"])
        unavailable = await client.post(f"{photo_path}/recover", json=payload, headers=admin)
        assert unavailable.status_code == 409
        assert unavailable.json()["error_code"] == "PHOTO_RECOVERY_UNAVAILABLE"
        assert (await client.get(photo_path, headers=admin)).status_code == 404
