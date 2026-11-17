"""Cross-project access regressions: C3 (photo IDOR), H14 (documents/updates), H15.

Each test builds two disjoint project teams and attacks project A's resources with
project B's credentials. The paired "owner still succeeds" assertions matter as much as
the denials: an over-broad scope check that locks out legitimate users is also a bug.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.database import AsyncSessionLocal, engine
from app.models.document import DocumentVersion
from app.models.user import User
from app.services.document_service import DocumentService
from tests.concurrency_helpers import error_codes, race_sessions, require_database, status_counts
from tests.test_daily_reports import (
    create_test_client,
    create_user,
    login_for_token,
    report_payload,
    setup_project_team,
    skip_if_database_unavailable,
)
from tests.test_documents import pdf_bytes
from tests.test_photos import jpeg_bytes

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def isolated_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


PHOTO_FEED: dict[str, str | int] = {"kind": "photo", "limit": 200}
LIST_ALL: dict[str, str | int] = {"limit": 200}


async def two_teams(client) -> tuple[dict, dict]:
    """Two independent projects, each with its own engineer/manager/supervisor/op."""
    return await setup_project_team(client), await setup_project_team(client)


async def upload_report_photo(client, team: dict) -> tuple[str, str]:
    report = (
        await client.post(
            "/api/v1/reports",
            json=report_payload(team["project_id"], team["supervisor_update_id"]),
            headers=auth(team["engineer_token"]),
        )
    ).json()
    uploaded = await client.post(
        "/api/v1/photos/upload",
        data={"entity_type": "daily_report", "entity_id": report["id"], "kind": "photo"},
        files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
        headers=auth(team["engineer_token"]),
    )
    assert uploaded.status_code == 201, uploaded.text
    return report["id"], uploaded.json()[0]["id"]


async def upload_document(client, team: dict, *, project_scoped: bool = True) -> dict:
    data = {"title": "WIR Zone A", "document_type": "wir"}
    if project_scoped:
        data["project_id"] = team["project_id"]
    response = await client.post(
        "/api/v1/documents",
        data=data,
        files={"file": ("wir.pdf", pdf_bytes("v1"), "application/pdf")},
        headers=auth(team["op_token"]),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_photo_idor_is_closed_for_every_read_and_delete_path() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        report_id, photo_id = await upload_report_photo(client, team_a)
        outsider = team_b["engineer_token"]

        for path in (
            f"/api/v1/photos/{photo_id}",
            f"/api/v1/photos/{photo_id}/download",
            f"/api/v1/photos/{photo_id}/thumbnail",
        ):
            response = await client.get(path, headers=auth(outsider))
            assert response.status_code == 404, (path, response.status_code, response.text)

        deleted = await client.delete(f"/api/v1/photos/{photo_id}", headers=auth(outsider))
        assert deleted.status_code == 404, deleted.text

        listed = await client.get(
            "/api/v1/photos",
            params={"entity_type": "daily_report", "entity_id": report_id},
            headers=auth(outsider),
        )
        assert listed.status_code == 404, listed.text

        # The owner is unaffected, and the photo really still exists (not soft-deleted).
        owner_get = await client.get(
            f"/api/v1/photos/{photo_id}", headers=auth(team_a["engineer_token"])
        )
        assert owner_get.status_code == 200
        owner_url = await client.get(
            f"/api/v1/photos/{photo_id}/thumbnail", headers=auth(team_a["engineer_token"])
        )
        assert owner_url.status_code == 200


async def test_recent_photo_feed_is_project_and_owner_scoped() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        _, photo_id = await upload_report_photo(client, team_a)

        outsider_feed = await client.get(
            "/api/v1/photos", params=PHOTO_FEED, headers=auth(team_b["engineer_token"])
        )
        assert outsider_feed.status_code == 200
        assert photo_id not in {item["id"] for item in outsider_feed.json()["items"]}

        # A manager of project B must not see project A's evidence either.
        manager_feed = await client.get(
            "/api/v1/photos", params=PHOTO_FEED, headers=auth(team_b["manager_token"])
        )
        assert manager_feed.status_code == 200
        assert photo_id not in {item["id"] for item in manager_feed.json()["items"]}

        # Company-wide roles keep the unrestricted feed.
        op_feed = await client.get(
            "/api/v1/photos", params=PHOTO_FEED, headers=auth(team_a["op_token"])
        )
        assert op_feed.status_code == 200
        assert photo_id in {item["id"] for item in op_feed.json()["items"]}

        accounts_email, accounts_password = await create_user("administrative_executive")
        accounts_token = await login_for_token(client, accounts_email, accounts_password)
        accounts_feed = await client.get(
            "/api/v1/photos", params=PHOTO_FEED, headers=auth(accounts_token)
        )
        assert accounts_feed.status_code == 200
        assert photo_id not in {item["id"] for item in accounts_feed.json()["items"]}
        assert (
            await client.get(f"/api/v1/photos/{photo_id}", headers=auth(accounts_token))
        ).status_code == 404

        supervisor = auth(team_a["supervisor_token"])
        supervisor_feed = await client.get("/api/v1/photos", params=PHOTO_FEED, headers=supervisor)
        assert supervisor_feed.status_code == 200
        assert supervisor_feed.json() == {"items": [], "total": 0}
        update_files = await client.get(
            "/api/v1/photos",
            params={
                "entity_type": "supervisor_update",
                "entity_id": team_a["supervisor_update_id"],
            },
            headers=supervisor,
        )
        assert update_files.status_code == 200

        _, own_photo_id = await upload_report_photo(client, team_b)
        feed = await client.get(
            "/api/v1/photos", params=PHOTO_FEED, headers=auth(team_b["manager_token"])
        )
        assert feed.status_code == 200
        ids = {item["id"] for item in feed.json()["items"]}
        assert own_photo_id in ids
        assert photo_id not in ids


async def test_dashboard_only_role_cannot_read_reports_and_evidence() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        report_id, photo_id = await upload_report_photo(client, team_a)
        other_report_id, _ = await upload_report_photo(client, team_b)
        admin_exec_email, admin_exec_password = await create_user("administrative_executive")
        admin_exec = auth(await login_for_token(client, admin_exec_email, admin_exec_password))

        for team, expected_id in ((team_a, report_id), (team_b, other_report_id)):
            reports = await client.get(
                "/api/v1/reports", params={"project_id": team["project_id"]}, headers=admin_exec
            )
            assert reports.status_code == 403
            assert reports.json()["error_code"] == "DAILY_REPORT_FORBIDDEN"
            detail = await client.get(f"/api/v1/reports/{expected_id}", headers=admin_exec)
            assert detail.status_code == 404

        photo_list = await client.get(
            "/api/v1/photos",
            params={"entity_type": "daily_report", "entity_id": report_id},
            headers=admin_exec,
        )
        assert photo_list.status_code == 404
        photo = await client.get(f"/api/v1/photos/{photo_id}", headers=admin_exec)
        assert photo.status_code == 404
        for variant in ("download", "thumbnail"):
            link = await client.get(f"/api/v1/photos/{photo_id}/{variant}", headers=admin_exec)
            assert link.status_code == 404

        draft_pdf = await client.get(f"/api/v1/reports/{report_id}/pdf", headers=admin_exec)
        assert draft_pdf.status_code == 404
        denied_update = await client.put(
            f"/api/v1/reports/{report_id}",
            json=report_payload(team_a["project_id"]),
            headers=admin_exec,
        )
        assert denied_update.status_code == 403
        denied_submit = await client.post(f"/api/v1/reports/{report_id}/submit", headers=admin_exec)
        assert denied_submit.status_code == 403
        denied_upload = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report_id, "kind": "photo"},
            files={"files": ("site.jpg", jpeg_bytes(), "image/jpeg")},
            headers=admin_exec,
        )
        assert denied_upload.status_code == 403
        denied_delete = await client.delete(f"/api/v1/photos/{photo_id}", headers=admin_exec)
        assert denied_delete.status_code == 403

        submitted = await client.post(
            f"/api/v1/reports/{report_id}/submit", headers=auth(team_a["engineer_token"])
        )
        assert submitted.status_code == 200, submitted.text
        decision = {"comments": "Ready for archive.", "target_covered": True}
        denied_approval = await client.post(
            f"/api/v1/reports/{report_id}/approve", json=decision, headers=admin_exec
        )
        assert denied_approval.status_code == 403
        approved = await client.post(
            f"/api/v1/reports/{report_id}/approve",
            json=decision,
            headers=auth(team_a["manager_token"]),
        )
        assert approved.status_code == 200, approved.text

        director_pdf = await client.get(
            f"/api/v1/reports/{report_id}/pdf", headers=auth(team_a["op_token"])
        )
        assert director_pdf.status_code == 200
        assert director_pdf.headers["content-type"] == "application/pdf"
        pdf = await client.get(f"/api/v1/reports/{report_id}/pdf", headers=admin_exec)
        assert pdf.status_code == 404
        assert director_pdf.content.startswith(b"%PDF-")
        assert director_pdf.content.rstrip().endswith(b"%%EOF")
        for outsider in (team_b["manager_token"], team_b["engineer_token"]):
            pdf = await client.get(f"/api/v1/reports/{report_id}/pdf", headers=auth(outsider))
            assert pdf.status_code == 404


async def test_recent_feed_rejects_non_report_entity_types() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, _ = await two_teams(client)
        for entity_type in ("project", "document", "supervisor_update"):
            response = await client.get(
                "/api/v1/photos",
                params={"entity_type": entity_type},
                headers=auth(team_a["engineer_token"]),
            )
            assert response.status_code == 422, (entity_type, response.text)
            assert response.json()["error_code"] == "ENTITY_ID_REQUIRED"


async def test_photo_upload_into_another_projects_report_is_rejected() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        report_id, _ = await upload_report_photo(client, team_a)

        response = await client.post(
            "/api/v1/photos/upload",
            data={"entity_type": "daily_report", "entity_id": report_id, "kind": "photo"},
            files={"files": ("intruder.jpg", jpeg_bytes(), "image/jpeg")},
            headers=auth(team_b["engineer_token"]),
        )
        assert response.status_code == 404, response.text


async def test_document_read_paths_are_project_scoped() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        document = await upload_document(client, team_a)
        document_id = document["id"]
        version_id = document["versions"][0]["id"]
        outsider = team_b["engineer_token"]

        for path in (
            f"/api/v1/documents/{document_id}",
            f"/api/v1/documents/{document_id}/versions",
            f"/api/v1/documents/{document_id}/download",
        ):
            response = await client.get(path, headers=auth(outsider))
            assert response.status_code == 404, (path, response.status_code, response.text)

        version_upload = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("intruder.pdf", pdf_bytes("v2"), "application/pdf")},
            headers=auth(outsider),
        )
        assert version_upload.status_code == 403, version_upload.text

        listed = await client.get("/api/v1/documents", params=LIST_ALL, headers=auth(outsider))
        assert listed.status_code == 200
        assert document_id not in {item["id"] for item in listed.json()["items"]}

        # Owner and company-wide roles are unaffected.
        assert (
            await client.get(
                f"/api/v1/documents/{document_id}", headers=auth(team_a["engineer_token"])
            )
        ).status_code == 200
        assert (
            await client.get(f"/api/v1/documents/{document_id}", headers=auth(team_a["op_token"]))
        ).status_code == 200
        assert (
            await client.get(
                f"/api/v1/documents/{document_id}/download",
                params={"version_id": version_id},
                headers=auth(team_a["manager_token"]),
            )
        ).status_code == 200


async def test_hr_executive_reader_has_only_approved_scoped_access() -> None:
    await skip_if_database_unavailable()
    async with create_test_client() as client:
        assigned, other = await two_teams(client)
        for team in (assigned, other):
            active = await client.patch(
                f"/api/v1/projects/{team['project_id']}",
                json={"status": "active"},
                headers=auth(team["op_token"]),
            )
            assert active.status_code == 200, active.text
        email, password = await create_user("hr_executive_reader")
        reader = auth(await login_for_token(client, email, password))
        identity = (await client.get("/api/v1/auth/me", headers=reader)).json()
        assert set(identity["permissions"]) == {
            "users:read", "dashboard:scoped", "reports:view", "documents:view"
        }
        directory = await client.get("/api/v1/users", headers=reader)
        assert directory.status_code == 200
        unassigned_dashboard = await client.get("/api/v1/dashboard/summary", headers=reader)
        assert unassigned_dashboard.json()["active_projects"] == 0

        membership = await client.post(
            f"/api/v1/projects/{assigned['project_id']}/members",
            json={"user_id": identity["id"], "role_in_project": "hr_executive_reader"},
            headers=auth(assigned["op_token"]),
        )
        assert membership.status_code == 201, membership.text
        allowed_report, _ = await upload_report_photo(client, assigned)
        foreign_report, _ = await upload_report_photo(client, other)
        allowed_document = await upload_document(client, assigned)
        foreign_document = await upload_document(client, other)
        company_document = await upload_document(client, assigned, project_scoped=False)
        dashboard = await client.get("/api/v1/dashboard/summary", headers=reader)
        assert dashboard.status_code == 200
        assert dashboard.json()["active_projects"] == 1
        report_list = await client.get("/api/v1/reports", params={"limit": 100}, headers=reader)
        assert report_list.status_code == 200
        assert {row["id"] for row in report_list.json()["items"]} == {allowed_report}
        assert (await client.get(f"/api/v1/reports/{allowed_report}", headers=reader)).is_success
        foreign = await client.get(f"/api/v1/reports/{foreign_report}", headers=reader)
        assert foreign.status_code in (403, 404)
        assert (
            await client.get(f"/api/v1/documents/{allowed_document['id']}", headers=reader)
        ).status_code == 200
        for document in (foreign_document, company_document):
            denied = await client.get(
                f"/api/v1/documents/{document['id']}/download", headers=reader
            )
            assert denied.status_code == 404

        for path in (
            "/api/v1/hr/employees",
            "/api/v1/hr/documents",
            "/api/v1/hr/payroll/runs",
            "/api/v1/audit-logs",
        ):
            assert (await client.get(path, headers=reader)).status_code == 403, path
        blocked_approval = await client.post(
            f"/api/v1/reports/{allowed_report}/approve",
            json={"comments": "Synthetic decision", "target_covered": True},
            headers=reader,
        )
        assert blocked_approval.status_code == 403
        assert (await client.post("/api/v1/users", json={}, headers=reader)).status_code == 403


async def test_company_wide_documents_are_hidden_from_project_roles() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, _ = await two_teams(client)
        document = await upload_document(client, team_a, project_scoped=False)
        document_id = document["id"]

        for token in (
            team_a["engineer_token"],
            team_a["manager_token"],
            team_a["supervisor_token"],
        ):
            response = await client.get(f"/api/v1/documents/{document_id}", headers=auth(token))
            assert response.status_code == 404, response.text

        listed = await client.get(
            "/api/v1/documents", params=LIST_ALL, headers=auth(team_a["engineer_token"])
        )
        assert document_id not in {item["id"] for item in listed.json()["items"]}

        assert (
            await client.get(f"/api/v1/documents/{document_id}", headers=auth(team_a["op_token"]))
        ).status_code == 200


async def test_supervisor_updates_are_scoped_and_unprivileged_role_is_denied() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        update_id = team_a["supervisor_update_id"]

        user_email, user_password = await create_user("administrative_executive")
        user_token = await login_for_token(client, user_email, user_password)
        denied = await client.get("/api/v1/supervisor-updates", headers=auth(user_token))
        assert denied.status_code == 403, denied.text
        assert denied.json()["error_code"] == "SUPERVISOR_UPDATE_FORBIDDEN"

        foreign = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": team_a["project_id"]},
            headers=auth(team_b["manager_token"]),
        )
        assert foreign.status_code == 404, foreign.text

        # Unfiltered manager list is limited to their own projects.
        own_feed = await client.get(
            "/api/v1/supervisor-updates", params=LIST_ALL, headers=auth(team_b["manager_token"])
        )
        assert own_feed.status_code == 200
        assert update_id not in {item["id"] for item in own_feed.json()["items"]}

        own_project_feed = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": team_b["project_id"], **LIST_ALL},
            headers=auth(team_b["manager_token"]),
        )
        assert own_project_feed.status_code == 200
        assert team_b["supervisor_update_id"] in {
            item["id"] for item in own_project_feed.json()["items"]
        }

        # Company-wide roles still see everything, including across projects.
        company_feed = await client.get(
            "/api/v1/supervisor-updates",
            params={"project_id": team_a["project_id"], **LIST_ALL},
            headers=auth(team_a["op_token"]),
        )
        assert company_feed.status_code == 200
        assert update_id in {item["id"] for item in company_feed.json()["items"]}


async def test_document_version_approval_requires_pending_and_project_scope() -> None:
    await skip_if_database_unavailable()

    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        document = await upload_document(client, team_a)
        document_id = document["id"]
        version_id = document["versions"][0]["id"]
        approve_path = f"/api/v1/documents/{document_id}/versions/{version_id}/approve"

        approver_email, approver_password = await create_user("managing_director")
        approver_token = await login_for_token(client, approver_email, approver_password)

        foreign_pm = await client.post(
            approve_path, json={"comments": "nope"}, headers=auth(team_b["manager_token"])
        )
        assert foreign_pm.status_code == 403, foreign_pm.text
        assert foreign_pm.json()["error_code"] == "PERMISSION_DENIED"

        self_approval = await client.post(
            approve_path, json={"comments": "not allowed"}, headers=auth(team_a["op_token"])
        )
        assert self_approval.status_code == 403, self_approval.text
        assert self_approval.json()["error_code"] == "DOCUMENT_SELF_APPROVAL_FORBIDDEN"

        approved = await client.post(
            approve_path, json={"comments": "ok"}, headers=auth(approver_token)
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["active_version"] == 1

        replay = await client.post(
            approve_path, json={"comments": "again"}, headers=auth(approver_token)
        )
        assert replay.status_code == 409, replay.text
        assert replay.json()["error_code"] == "DOCUMENT_VERSION_NOT_PENDING"

        # A company-wide (project_id IS NULL) document is not approvable by a PM.
        global_document = await upload_document(client, team_a, project_scoped=False)
        global_approve = await client.post(
            f"/api/v1/documents/{global_document['id']}/versions/"
            f"{global_document['versions'][0]['id']}/approve",
            json={"comments": "pm cannot"},
            headers=auth(team_a["manager_token"]),
        )
        assert global_approve.status_code == 403, global_approve.text
        assert global_approve.json()["error_code"] == "PERMISSION_DENIED"
        global_ok = await client.post(
            f"/api/v1/documents/{global_document['id']}/versions/"
            f"{global_document['versions'][0]['id']}/approve",
            json={"comments": "op can"},
            headers=auth(approver_token),
        )
        assert global_ok.status_code == 200, global_ok.text


async def test_concurrent_document_approvals_activate_exactly_one_version() -> None:
    """H15 race: three approvers, one pending version, one active row afterwards."""
    await require_database()

    async with create_test_client() as client:
        team_a, _ = await two_teams(client)
        document = await upload_document(client, team_a)
        approver_email, approver_password = await create_user("managing_director")
        approver_token = await login_for_token(client, approver_email, approver_password)
        document_id = UUID(document["id"])
        revised = await client.post(
            f"/api/v1/documents/{document_id}/versions",
            files={"file": ("wir-rev2.pdf", pdf_bytes("v2"), "application/pdf")},
            headers=auth(team_a["op_token"]),
        )
        assert revised.status_code == 200, revised.text
        pending = max(revised.json()["versions"], key=lambda item: item["version"])
        assert pending["status"] == "pending_approval"
        version_id = UUID(pending["id"])
        me = (await client.get("/api/v1/auth/me", headers=auth(approver_token))).json()
        manager_id = UUID(me["id"])

    async def approve(session):
        actor = await session.scalar(select(User).where(User.id == manager_id))
        assert actor is not None
        approved = await DocumentService(session).approve_version(
            document_id, version_id, actor, "race"
        )
        return approved.status

    results = await race_sessions(approve, approve, approve)
    assert status_counts(results) == {"active": 1, 409: 2}, results
    assert error_codes(results) == ["DOCUMENT_VERSION_NOT_PENDING"] * 2, results

    async with engine.connect() as connection:
        active = await connection.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.status == "active",
                DocumentVersion.deleted_at.is_(None),
            )
        )
    assert active == 1


async def test_disabled_account_and_midflight_access_revision_revocation_deny_access() -> None:
    await require_database()
    async with create_test_client() as client:
        team_a, team_b = await two_teams(client)
        doc = await upload_document(client, team_a)
        doc_id = doc["id"]

        # Same role (quantity_surveyor / site_supervisor), other project cannot read document.
        cross_doc = await client.get(
            f"/api/v1/documents/{doc_id}",
            headers=auth(team_b["supervisor_token"]),
        )
        assert cross_doc.status_code in {403, 404}

        # Disabled account is denied even with an unexpired bearer token.
        me = (await client.get("/api/v1/auth/me", headers=auth(team_a["op_token"]))).json()
        async with AsyncSessionLocal() as session:
            user = await session.get(User, UUID(me["id"]))
            assert user is not None
            user.is_active = False
            await session.commit()
        denied_disabled = await client.get("/api/v1/projects", headers=auth(team_a["op_token"]))
        assert denied_disabled.status_code == 401

        # Mid-flight access_revision bump / role downgrade invalidates existing bearer token.
        me_b = (await client.get("/api/v1/auth/me", headers=auth(team_b["op_token"]))).json()
        async with AsyncSessionLocal() as session:
            user_b = await session.get(User, UUID(me_b["id"]))
            assert user_b is not None
            user_b.role = "site_supervisor"
            user_b.access_revision += 1
            await session.commit()
        denied_revoked = await client.get("/api/v1/projects", headers=auth(team_b["op_token"]))
        assert denied_revoked.status_code == 401
