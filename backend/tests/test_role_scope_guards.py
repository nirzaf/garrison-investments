import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval import Approval
from app.models.daily_report import DailyReport
from app.models.notification import Notification
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.services.approval_service import ApprovalService
from app.services.authorization import (
    accessible_project_ids,
    document_scope_filter,
    ensure_project_access,
)
from app.services.dashboard_service import DashboardService
from app.services.project_service import ProjectService
from app.services.report_service import ReportService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import COMPANY_RESOURCE_ROLES

pytestmark = pytest.mark.asyncio
RETIRED_ROLE_KEYS = json.loads(
    Path(__file__).with_name("business_role_matrix.json").read_text()
)["retired_roles"]


@pytest.mark.parametrize("retired_role", RETIRED_ROLE_KEYS)
async def test_retired_role_fails_before_project_or_document_scope_lookup(
    retired_role: str,
) -> None:
    actor = User(role=retired_role)

    for operation in (
        accessible_project_ids(cast(AsyncSession, None), actor),
        ensure_project_access(cast(AsyncSession, None), uuid4(), actor),
        document_scope_filter(cast(AsyncSession, None), actor),
    ):
        with pytest.raises(AppException) as exc_info:
            await operation
        assert exc_info.value.status_code == 403
        assert exc_info.value.error_code == "INVALID_ROLE"


async def test_project_service_rechecks_read_permission_before_repository_access() -> None:
    actor = User(role="quantity_surveyor")
    service = ProjectService(cast(AsyncSession, None))

    with pytest.raises(AppException) as list_error:
        await service.list_projects(
            current_user=actor,
            status=None,
            search=None,
            limit=100,
            offset=0,
        )
    assert list_error.value.status_code == 403

    with pytest.raises(AppException) as detail_error:
        await service.get_project_detail(uuid4(), actor)
    assert detail_error.value.status_code == 403


async def test_report_submitter_can_recover_own_final_report_but_not_another_authors(
    monkeypatch,
) -> None:
    service = ReportService(cast(AsyncSession, None))
    actor = User(role="quantity_surveyor")

    async def project_member(_project_id, _actor):
        return SimpleNamespace(id=uuid4())

    monkeypatch.setattr(service, "_ensure_project_member", project_member)
    own_report = cast(
        DailyReport,
        SimpleNamespace(engineer_id=actor.id, project_id=uuid4(), status="approved"),
    )
    await service._ensure_report_access(own_report, actor)

    other_report = cast(
        DailyReport,
        SimpleNamespace(engineer_id=uuid4(), project_id=uuid4(), status="draft"),
    )
    with pytest.raises(NotFoundException):
        await service._ensure_report_access(other_report, actor)


async def test_projectless_approval_fallback_uses_only_company_resource_roles(monkeypatch) -> None:
    class EmptySession:
        async def scalar(self, _statement):
            return None

    service = ApprovalService(cast(AsyncSession, EmptySession()))
    observed_roles: set[str] | None = None

    async def no_active_company_user(roles, *, excluded_user_ids=None):
        nonlocal observed_roles
        observed_roles = set(roles)
        assert excluded_user_ids
        return None

    monkeypatch.setattr(service, "_first_active_role_user", no_active_company_user)
    payload = ApprovalCreateRequest(
        request_type="daily_report",
        request_id=uuid4(),
        project_id=uuid4(),
        title="Daily report",
    )

    with pytest.raises(AppException) as exc_info:
        await service._resolve_approver(payload, User(role="site_supervisor"))

    assert exc_info.value.error_code == "APPROVER_NOT_CONFIGURED"
    assert observed_roles == COMPANY_RESOURCE_ROLES


async def test_unknown_generic_approval_creation_and_override_are_denied() -> None:
    service = ApprovalService(cast(AsyncSession, None))
    actor = User(role="managing_director")
    payload = ApprovalCreateRequest(
        request_type="project_change",
        request_id=uuid4(),
        project_id=uuid4(),
        title="Unsupported generic request",
    )

    with pytest.raises(AppException) as create_error:
        await service._resolve_approver(payload, actor)
    assert create_error.value.error_code == "APPROVAL_TYPE_FORBIDDEN"

    with pytest.raises(AppException) as override_error:
        await service.override(uuid4(), actor, "approved", "No override permission exists.")
    assert override_error.value.error_code == "APPROVAL_OVERRIDE_FORBIDDEN"


async def test_unknown_generic_approval_type_has_no_decision_recipient() -> None:
    service = ApprovalService(cast(AsyncSession, None))
    approval = cast(Approval, SimpleNamespace(request_type="project_change"))

    assert not await service._approval_recipient_has_current_scope(approval, uuid4())


async def test_queued_generic_approval_email_is_not_delivered(monkeypatch) -> None:
    service = ApprovalService(cast(AsyncSession, None))
    recipient_id = uuid4()
    approval = cast(
        Approval,
        SimpleNamespace(
            id=uuid4(),
            request_type="project_change",
            status="pending",
            approver_id=recipient_id,
        ),
    )

    async def get_by_id(_approval_id, *, for_update=False):
        return approval

    monkeypatch.setattr(service.approvals, "get_by_id", get_by_id)
    notification = cast(
        Notification,
        SimpleNamespace(
            notification_type="approval",
            reference_type="approvals",
            reference_id=approval.id,
            title="Approval pending",
            user_id=recipient_id,
        ),
    )

    assert not await service.can_deliver_scheduled_email(notification)


async def test_dashboard_separates_company_aggregates_from_report_details(monkeypatch) -> None:
    service = DashboardService(cast(AsyncSession, None))
    assigned_project = uuid4()
    recent_scopes: list[list | None] = []

    async def visible_project_ids(_actor):
        return None

    async def count(_scope, *_args):
        return 7

    async def count_notifications(_actor):
        return 0

    async def assigned_project_ids(_actor):
        return [assigned_project]

    async def recent_activity(scope):
        recent_scopes.append(scope)
        return ["R-1: submitted"]

    monkeypatch.setattr(service, "_visible_project_ids", visible_project_ids)
    monkeypatch.setattr(service, "_count_projects", count)
    monkeypatch.setattr(service, "_count_reports", count)
    monkeypatch.setattr(service, "_count_documents", count)
    monkeypatch.setattr(service, "_count_notifications", count_notifications)
    monkeypatch.setattr(service, "_assigned_project_ids", assigned_project_ids)
    monkeypatch.setattr(service, "_recent_activity", recent_activity)

    hr_summary = await service.summary(User(role="hr_manager"))
    ae_summary = await service.summary(User(role="administrative_executive"))
    director_summary = await service.summary(User(role="managing_director"))

    assert hr_summary.active_projects == 7  # company aggregate is permitted by D09
    assert hr_summary.recent_activity == ["R-1: submitted"]
    assert ae_summary.active_projects == 7
    assert ae_summary.recent_activity == []  # AE has no reports:view grant
    assert director_summary.recent_activity == ["R-1: submitted"]
    assert recent_scopes == [[assigned_project], None]
