from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from fastapi import UploadFile
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import AsyncSessionLocal, engine
from app.models.daily_report import DailyReport
from app.models.photo import Photo
from app.models.user import User
from app.services.photo_service import PhotoService
from app.services.report_service import ReportService
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
from tests.test_inventory_accounting import race_with_parent_lock

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
        upload_payload = {
            "entity_type": "daily_report",
            "entity_id": report["id"],
            "kind": "photo",
            "expected_report_revision": str(report["revision"]),
        }
        upload_headers = {
            "Authorization": f"Bearer {setup['engineer_token']}",
            "Idempotency-Key": str(uuid4()),
        }
        upload_response = await client.post(
            "/api/v1/photos/upload",
            data=upload_payload,
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers=upload_headers,
        )

        assert upload_response.status_code == 201
        assert upload_response.headers["X-Report-Revision"] == str(report["revision"] + 1)
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
        # Submit-only authors can retrieve evidence through their own report, but do not
        # receive the general cross-report photo feed.
        assert recent_response.json()["total"] == 0
        assert entity_response.status_code == 200
        assert entity_response.json()["total"] == 1
        assert entity_response.json()["items"][0]["id"] == photo["id"]

        url_response = await client.get(
            f"/api/v1/photos/{photo['id']}/thumbnail",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )

        assert url_response.status_code == 200
        assert "url" in url_response.json()

        submitted = await client.post(
            f"/api/v1/reports/{report['id']}/submit",
            headers={"Authorization": f"Bearer {setup['engineer_token']}"},
        )
        assert submitted.json()["revision"] == report["revision"] + 2
        replay = await client.post(
            "/api/v1/photos/upload",
            data=upload_payload,
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers=upload_headers,
        )
        assert replay.status_code == 201
        assert replay.json()[0]["id"] == photo["id"]
        assert replay.headers["X-Report-Revision"] == upload_response.headers["X-Report-Revision"]
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


async def test_photo_quota_serializes_concurrent_uploads() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        director_email, director_password = await create_user("managing_director")
        director_token = await login_for_token(client, director_email, director_password)
        director = {"Authorization": f"Bearer {director_token}"}
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
        first, *_ = upload.json()
        first_id = UUID(first["id"])
        delete_first = await client.delete(f"/api/v1/photos/{first_id}", headers=engineer)
        assert delete_first.status_code == 204, delete_first.text

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
        denied = await client.get(
            "/api/v1/photos", params={**owner, "deleted": True}, headers=director
        )
        assert denied.status_code == 403
        denied = await client.post(f"/api/v1/photos/{first_id}/recover", headers=director)
        assert denied.status_code == 403
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


@pytest.mark.parametrize("submit_first", [True, False], ids=["submit-first", "upload-first"])
async def test_photo_upload_and_report_submission_serialize(submit_first: bool) -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        created = await client.post(
            "/api/v1/reports",
            json=report_payload(team["project_id"], team["supervisor_update_id"]),
            headers=engineer,
        )
        assert created.status_code == 201
        report = created.json()
        report_id = UUID(report["id"])
        engineer_id = UUID(report["engineer_id"])
        first_photo = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": str(report_id), "kind": "photo"},
            files={"files": ("existing.jpg", jpeg_bytes(), "image/jpeg")},
            headers=engineer,
        )
        assert first_photo.status_code == 201
        before_revision = int(first_photo.headers["X-Report-Revision"])

        async def submit(session: AsyncSession) -> int:
            actor = await session.get_one(User, engineer_id)
            submitted = await ReportService(session).submit_report(report_id, actor)
            assert submitted.status == "submitted"
            return 200

        async def upload(session: AsyncSession) -> int:
            actor = await session.get_one(User, engineer_id)
            await PhotoService(session).upload(
                file=UploadFile(BytesIO(jpeg_bytes()), filename="contending.jpg"),
                entity_type="daily_report",
                entity_id=report_id,
                kind="photo",
                caption=None,
                actor=actor,
            )
            return 201

        parent = select(DailyReport.id).where(DailyReport.id == report_id)
        operations = (submit, upload) if submit_first else (upload, submit)
        results = await race_with_parent_lock(parent, *operations)
        if submit_first:
            assert status_counts(results) == {200: 1, 409: 1}, results
            assert error_codes(results) == ["PHOTO_UPLOAD_LOCKED"]
        else:
            assert results == [201, 200], results

        async with AsyncSessionLocal() as session:
            saved_report = await session.get_one(DailyReport, report_id)
            assert saved_report.status == "submitted"
            assert saved_report.revision == before_revision + (1 if submit_first else 2)
            photos = (
                await session.scalars(
                    select(Photo).where(
                        Photo.entity_type == "daily_report", Photo.entity_id == report_id
                    )
                )
            ).all()
            assert all(photo.deleted_at is None for photo in photos)
            names = ["existing.jpg"] if submit_first else ["contending.jpg", "existing.jpg"]
            assert sorted(photo.original_name for photo in photos) == names
            assert all(
                photo.report_revision == before_revision + (photo.original_name == "contending.jpg")
                for photo in photos
            )
            expected_objects = {
                path
                for photo in photos
                for path in (photo.storage_path, photo.compressed_path, photo.thumbnail_path)
                if path
            }
        settings = get_settings()
        actual_objects = {
            item.object_name
            for item in minio_client(settings).list_objects(
                settings.minio_bucket, prefix=f"daily_report/{report_id}/", recursive=True
            )
        }
        assert len(expected_objects) == 3 * len(names)
        assert actual_objects == expected_objects


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
                "activity_scope": "Counting material received",
                "remaining_work": "Finish inspection",
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
            f"/api/v1/supervisor-updates/{update_id}/submit",
            json={"expected_revision": 1},
            headers=actor,
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


async def test_director_cannot_use_retired_admin_media_override() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        director_email, director_password = await create_user("managing_director")
        director_token = await login_for_token(client, director_email, director_password)
        director = {"Authorization": f"Bearer {director_token}"}
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

        # The ten-role policy has no technical Admin role or implicit admin override.
        # A director may view company-wide evidence but cannot rewrite finalized evidence
        # without an explicitly granted domain operation.
        no_reason = await client.delete(photo_path, headers=director)
        assert no_reason.status_code == 404, no_reason.text
        removal = await client.request(
            "DELETE",
            photo_path,
            json={"reason": "Synthetic evidence reconciliation."},
            headers=director,
        )
        assert removal.status_code == 404, removal.text
        forbidden_recovery = await client.post(
            f"{photo_path}/recover",
            json={"reason": "Synthetic evidence confirmed."},
            headers=director,
        )
        assert forbidden_recovery.status_code == 403, forbidden_recovery.text
        retained = await client.get(photo_path, headers=engineer)
        assert retained.status_code == 200
        assert retained.json()["deleted_at"] is None
        assert (await client.get(photo_path, headers=director)).status_code == 200


async def test_unclassified_photo_metadata_and_urls_are_restricted_until_review() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        team = await setup_project_team(client)
        engineer = {"Authorization": f"Bearer {team['engineer_token']}"}
        report_response = await client.post(
            "/api/v1/reports",
            json=report_payload(team["project_id"], team["supervisor_update_id"]),
            headers=engineer,
        )
        assert report_response.status_code == 201, report_response.text
        report = report_response.json()
        uploaded = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
            files={"files": ("restricted.jpg", jpeg_bytes(), "image/jpeg")},
            headers=engineer,
        )
        assert uploaded.status_code == 201, uploaded.text
        assert uploaded.headers["cache-control"] == "no-store"
        photo = uploaded.json()[0]
        assert photo["classification"] == "unclassified"

        manager = {"Authorization": f"Bearer {team['manager_token']}"}
        for path in (
            f"/api/v1/photos/{photo['id']}",
            f"/api/v1/photos/{photo['id']}/download",
            f"/api/v1/photos/{photo['id']}/thumbnail",
        ):
            denied = await client.get(path, headers=manager)
            assert denied.status_code == 404, (path, denied.text)

        reviewer_email, reviewer_password = await create_user("managing_director")
        reviewer_token = await login_for_token(client, reviewer_email, reviewer_password)
        reviewer = {"Authorization": f"Bearer {reviewer_token}"}
        listed = await client.get("/api/v1/photos", headers=reviewer)
        assert listed.status_code == 200, listed.text
        assert listed.headers["cache-control"] == "no-store"
        assert photo["id"] in {item["id"] for item in listed.json()["items"]}
        reviewed = await client.patch(
            f"/api/v1/photos/{photo['id']}/classification",
            json={"classification": "operational", "reason": "Verified site photo."},
            headers=reviewer,
        )
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()["classification"] == "operational"
        thumbnail = await client.get(
            f"/api/v1/photos/{photo['id']}/thumbnail", headers=manager
        )
        assert thumbnail.status_code == 200
        download = await client.get(f"/api/v1/photos/{photo['id']}/download", headers=manager)
        assert download.headers["cache-control"] == "no-store"
