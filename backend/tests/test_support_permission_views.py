from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select, text, update

from app.database import AsyncSessionLocal
from app.models.activity_log import ActivityLog
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.support_case_actions import SupportCaseAction, SupportCaseProject
from app.models.support_cases import (
    SupportCase,
    SupportCaseMember,
    SupportCaseRequest,
    SupportOperatorGrant,
)
from app.models.support_directory import SupportCaseSubject
from app.models.support_permission_view import SupportPermissionViewEvent
from app.models.user import User
from app.utils.permissions import (
    ROLE_GROUP_PROJECT_MANAGER,
    ROLE_HR_EXECUTIVE,
    ROLE_MANAGING_DIRECTOR,
)
from app.utils.security import utc_now
from tests.test_auth import skip_if_database_unavailable
from tests.test_support_custody import login
from tests.test_support_identity import API, client, sign
from tests.test_support_identity import enabled as enabled
from tests.test_support_identity import isolated_engine_pool as isolated_engine_pool


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
@pytest.mark.parametrize("kind", ["permission_view", "request_summary", "navigation_view"])
async def test_support_view_requires_live_review_and_the_requesters_session(kind: str) -> None:
    await skip_if_database_unavailable()
    async with client() as maker, client() as reviewer, client() as account_operator:
        maker_identity = await login(maker, custodian=False)
        reviewer_identity = await login(reviewer, custodian=False)
        account_identity = await login(account_operator, custodian=False)
        case_id, subject_id = uuid4(), uuid4()
        event_id, wrong_actor_event, unlinked_event = uuid4(), uuid4(), uuid4()
        request_ref = str(uuid4())
        async with AsyncSessionLocal() as db:
            db.add(
                User(
                    id=subject_id,
                    full_name="Synthetic private subject",
                    email=f"{subject_id}@example.com",
                    role=ROLE_HR_EXECUTIVE,
                    password_hash="synthetic-password-hash",
                )
            )
            db.add(
                SupportCase(
                    id=case_id,
                    owner_id=maker_identity[0],
                    external_ref=f"case-{case_id}",
                    reason_code="access",
                    status="open",
                    severity="medium",
                )
            )
            await db.flush()
            db.add(SupportCaseSubject(case_id=case_id, user_id=subject_id))
            for identity in (maker_identity, reviewer_identity, account_identity):
                db.add(SupportCaseMember(case_id=case_id, operator_id=identity[0]))
                db.add(
                    SupportOperatorGrant(
                        operator_id=identity[0],
                        capability="account.request"
                        if identity is account_identity
                        else "simulation.start",
                    )
                )
            if kind == "request_summary":
                for record, source_actor in (
                    (event_id, subject_id),
                    (wrong_actor_event, None),
                    (unlinked_event, subject_id),
                ):
                    db.add(
                        ActivityLog(
                            id=record,
                            request_id=request_ref,
                            user_id=source_actor,
                            entity_type="request",
                            action="http.request",
                            http_method="GET",
                            status_code=403,
                            endpoint="/private/synthetic-path",
                            context_payload={"sensitive": "synthetic secret"},
                        )
                    )
                    if record != unlinked_event:
                        db.add(
                            SupportCaseAction(
                                id=uuid4(),
                                case_id=case_id,
                                requester_id=maker_identity[0],
                                reviewer_id=reviewer_identity[0],
                                source_event_id=record,
                                source_request_id=request_ref,
                                source_status=403,
                                kind="evidence_link",
                                case_revision=1,
                                requester_epoch=1,
                                expires_at=utc_now() + timedelta(minutes=5),
                                applied_at=utc_now(),
                            )
                        )
                db.add(SupportCaseRequest(case_id=case_id, request_id=request_ref))
            await db.commit()

        root = f"{API}/cases/{case_id}/account-actions"
        payload = {
            "kind": kind,
            "case_revision": 1,
            "user_revision": 0,
            "user_id": str(subject_id),
            "reason": "Synthetic reviewed permission explanation",
        }
        if kind == "permission_view":
            payload.update(reason_code="permission_triage", permission_key="projects:read")
        elif kind == "request_summary":
            payload.update(reason_code="request_triage", source_event_id=str(event_id))
        else:
            payload.update(reason_code="permission_triage")
        headers = {"Idempotency-Key": str(uuid4())}
        assert (await account_operator.post(root, json=payload, headers=headers)).status_code == 404
        if kind == "permission_view":
            assert (
                await maker.post(
                    root, json={**payload, "permission_key": "unknown:permission"}, headers=headers
                )
            ).status_code == 422
        elif kind == "request_summary":
            for entry in (wrong_actor_event, unlinked_event):
                assert (
                    await maker.post(
                        root, json={**payload, "source_event_id": str(entry)}, headers=headers
                    )
                ).status_code == 404
        else:
            assert (
                await maker.post(root, json={**payload, "permission_key": "projects:read"},
                                 headers=headers)
            ).status_code == 422
        proposed = await maker.post(root, json=payload, headers=headers)
        assert proposed.status_code == 201, proposed.text
        action = proposed.json()
        view_id = action["id"]
        decision = f"{root}/{view_id}"
        view_path = f"{API}/views/{view_id}"
        adapters = {
            "permission_view": "permission-explanation",
            "request_summary": "request-summary",
            "navigation_view": "navigation",
        }
        adapter = adapters[kind]
        projection = f"{view_path}/projection/{adapter}"
        assert (await maker.get(projection)).status_code == 404
        assert (await maker.post(f"{decision}/review/options")).status_code == 403
        assert (await account_operator.post(f"{decision}/review/options")).status_code in {403, 404}
        assert (await maker.post(f"{decision}/execute/options")).status_code == 409

        review = await reviewer.post(f"{decision}/review/options")
        assert review.status_code == 200 and review.json()["required_reviews"] == 1
        review_result = await reviewer.post(
            f"{decision}/review",
            json={
                **sign(review.json(), *reviewer_identity, counter=2),
                "expected_digest": action["digest"],
            },
        )
        assert review_result.status_code == 200, review_result.text
        execute = await maker.post(f"{decision}/execute/options")
        assert execute.status_code == 200, execute.text
        executed = await maker.post(
            f"{decision}/execute",
            json={
                **sign(execute.json(), *maker_identity, counter=2),
                "expected_digest": action["digest"],
            },
        )
        assert executed.status_code == 200, executed.text
        assert (await reviewer.get(projection)).status_code == 404
        for other_adapter in set(adapters.values()) - {adapter}:
            assert (await maker.get(f"{view_path}/projection/{other_adapter}")).status_code == 404
        read = await maker.get(projection)
        assert read.status_code == 200 and read.headers["cache-control"] == "no-store", read.text
        result = read.json()
        fields = {
            "view_id",
            "case_id",
            "operator_id",
            "subject_id",
            "expires_at",
            "adapter",
        }
        assert result["view_id"] == view_id
        assert result["subject_id"] == str(subject_id)
        if kind == "permission_view":
            assert set(result) == fields | {"scope", "permission_key", "allowed"}
            assert result["scope"] == "role" and result["allowed"] is False
        elif kind == "request_summary":
            assert set(result) == fields | {"request_ref", "method", "status_code", "occurred_at"}
            assert result["request_ref"] == request_ref
            assert result["method"] == "GET" and result["status_code"] == 403
            assert "synthetic-path" not in read.text and "synthetic secret" not in read.text
            async with AsyncSessionLocal() as db:
                source = await db.get(ActivityLog, event_id)
                assert source is not None
                archived_at = utc_now()
                source.storage_tier = "archive"
                source.archived_at = archived_at
                source.retention_until = archived_at - timedelta(seconds=1)
                await db.flush()
                await db.execute(
                    text("SELECT set_config('garrison.audit_retention_purge', 'allow', true)")
                )
                await db.execute(delete(ActivityLog).where(ActivityLog.id == event_id))
                await db.commit()
            assert (await maker.get(projection)).status_code == 404
        else:
            assert set(result) == fields | {"routes"}
            assert all(set(route) == {"route_id", "visible"} for route in result["routes"])
            assert {route["route_id"] for route in result["routes"] if route["visible"]} == {
                "dashboard", "reports", "supervisor-updates", "documents", "my-hr",
                "photos", "approvals", "roles", "manual", "users",
            }
            assert {"projects", "hr-workforce", "employee-relations", "security"} <= {
                route["route_id"] for route in result["routes"] if not route["visible"]
            }

        assert (await reviewer.post(f"{view_path}/end")).status_code == 404
        assert (await maker.post(f"{view_path}/end")).status_code == 204
        assert (await maker.get(projection)).status_code == 409
        assert (await maker.post(f"{view_path}/end")).status_code == 204
        async with AsyncSessionLocal() as db:
            user = await db.get(User, subject_id)
            assert user is not None and user.access_revision == 0 and user.is_active
            events = list(
                await db.scalars(
                    select(SupportPermissionViewEvent.event)
                    .where(SupportPermissionViewEvent.view_id == UUID(view_id))
                    .order_by(SupportPermissionViewEvent.occurred_at)
                )
            )
            assert events == ["opened", "read", "ended"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("isolated_engine_pool", "enabled")
@pytest.mark.parametrize(
    ("kind", "role"),
    [
        ("project_list", ROLE_GROUP_PROJECT_MANAGER),
        ("project_list", ROLE_MANAGING_DIRECTOR),
        ("project_detail", ROLE_GROUP_PROJECT_MANAGER),
    ],
)
async def test_reviewed_project_projection_intersects_live_scope(kind: str, role: str) -> None:
    await skip_if_database_unavailable()
    async with client() as maker, client() as reviewer:
        maker_key = await login(maker, custodian=False)
        reviewer_key = await login(reviewer, custodian=False)
        case_id, subject_id = uuid4(), uuid4()
        project_id, hidden_id, outside_id = sorted([uuid4(), uuid4(), uuid4()])
        async with AsyncSessionLocal() as db:
            db.add_all([
                User(id=subject_id, full_name="Private person", email=f"{subject_id}@example.com",
                     role=role, password_hash="synthetic-password-hash"),
                SupportCase(
                    id=case_id, owner_id=maker_key[0], external_ref=f"case-{case_id}",
                    reason_code="access", status="open", severity="medium",
                ),
                *[
                    Project(
                        id=pid, name="Private project name", code=pid.hex[:12],
                        scope_of_work="Private scope", target_end_date=date(2030, 1, 1),
                        status=status,
                    )
                    for pid, status in [(project_id, "active"), (hidden_id, "on_hold"),
                                        (outside_id, "planning")]
                ],
            ])
            await db.flush()
            db.add_all([
                SupportCaseSubject(case_id=case_id, user_id=subject_id),
                SupportCaseProject(case_id=case_id, project_id=project_id),
                SupportCaseProject(case_id=case_id, project_id=hidden_id),
                ProjectMember(project_id=project_id, user_id=subject_id),
                ProjectMember(project_id=outside_id, user_id=subject_id),
                ProjectMilestone(project_id=project_id, name="Private milestone"),
                ProjectMilestone(project_id=project_id, name="Removed", deleted_at=utc_now()),
                ProjectMilestone(project_id=outside_id, name="Unrelated milestone"),
                *[ProjectTask(project_id=project_id, name="Private task") for _ in range(101)],
            ])
            for operator, _, _ in (maker_key, reviewer_key):
                db.add(SupportCaseMember(case_id=case_id, operator_id=operator))
                db.add(SupportOperatorGrant(operator_id=operator, capability="simulation.start"))
            await db.commit()

        root = f"{API}/cases/{case_id}/account-actions"
        payload = {
            "kind": kind, "case_revision": 1, "user_revision": 0, "user_id": str(subject_id),
            "reason": "Review visible project boundaries", "reason_code": "permission_triage",
        }
        if kind == "project_detail":
            for inaccessible in (hidden_id, outside_id, uuid4()):
                denied = await maker.post(
                    root, json={**payload, "project_id": str(inaccessible)},
                    headers={"Idempotency-Key": str(uuid4())},
                )
                assert denied.status_code == 404
            payload["project_id"] = str(project_id)
        opened = await maker.post(root, json=payload, headers={"Idempotency-Key": str(uuid4())})
        assert opened.status_code == 201, opened.text
        view_id = opened.json()["id"]
        proof_path = f"{root}/{view_id}"
        digest = opened.json()["digest"]
        for actor, key, stage in [(reviewer, reviewer_key, "review"),
                                  (maker, maker_key, "execute")]:
            options = await actor.post(f"{proof_path}/{stage}/options")
            assert options.status_code == 200, options.text
            confirmed = await actor.post(
                f"{proof_path}/{stage}",
                json={**sign(options.json(), *key, counter=2), "expected_digest": digest},
            )
            assert confirmed.status_code == 200, confirmed.text

        projection = f"{API}/views/{view_id}/projection"
        chosen = "project-detail-summary" if kind == "project_detail" else "project-list"
        wrong = "project-list" if kind == "project_detail" else "project-detail-summary"
        assert (await maker.get(f"{projection}/{wrong}")).status_code == 404
        assert (await reviewer.get(f"{projection}/{chosen}")).status_code == 404
        response = await maker.get(f"{projection}/{chosen}")
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        for marker in ("Private", str(project_id), str(hidden_id), str(outside_id)):
            assert marker not in response.text
        result = response.json()
        assert result["adapter"] == chosen

        project = {"label": "Project 01", "status": "active"}
        if kind == "project_detail":
            assert result["project"] == {
                **project, "milestones": 1, "tasks": 100, "counts_capped": True,
            }
        else:
            assert result["projects"] == (
                [project, {"label": "Project 02", "status": "on_hold"}]
                if role == ROLE_MANAGING_DIRECTOR else [project]
            )

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ProjectMember).where(ProjectMember.project_id == project_id)
                .values(deleted_at=utc_now())
            )
            await db.commit()
        after_revocation = await maker.get(f"{projection}/{chosen}")
        if role == ROLE_GROUP_PROJECT_MANAGER:
            assert after_revocation.status_code == 404
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(ProjectMember).where(ProjectMember.project_id == project_id)
                    .values(deleted_at=None)
                )
                await db.commit()
            assert (await maker.get(f"{projection}/{chosen}")).status_code == 409
        else:
            assert after_revocation.status_code == 200
            assert after_revocation.json()["projects"] == result["projects"]
