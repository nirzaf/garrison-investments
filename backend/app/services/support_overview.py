"""Fixed, capability-gated oversight projections for the dedicated support portal."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.business_policy import DEFAULT_BUSINESS_CURRENCY
from app.config import get_settings
from app.models.approval import Approval
from app.models.document import Document, DocumentVersion
from app.models.finance import Invoice
from app.models.hr import HrEmployee, HrOnboardingCase, HrPayrollPolicy
from app.models.inventory import (
    InventoryItem,
    InventoryLocationStock,
    InventoryMovement,
    MaterialRequest,
    StorageLocation,
)
from app.models.project import Project
from app.models.project_milestone import ProjectMilestone
from app.models.project_task import ProjectTask
from app.models.supplier import Supplier
from app.models.support_case_actions import SupportCaseProject
from app.models.support_cases import SupportCase, SupportCaseMember, SupportOperatorGrant
from app.models.support_oversight import SupportOversightEvent
from app.schemas.support_oversight import (
    ApprovalWorkflowBucket,
    CaseMaskedProjectSummary,
    MetricState,
    OversightMetric,
    OversightScope,
    ProjectStatusBucket,
    SupportApprovalsOverviewRead,
    SupportCompanyOverviewRead,
    SupportDocumentsOverviewRead,
    SupportFinanceOverviewRead,
    SupportInventoryOverviewRead,
    SupportPolicyExplainQuery,
    SupportPolicyExplainRead,
    SupportProjectsOverviewRead,
    SupportSuppliersOverviewRead,
    SupportWorkforceOverviewRead,
    WorkforceBucket,
    WorkforceProjectCount,
)
from app.services.finance_service import NON_BILLABLE_INVOICE_STATUSES
from app.services.project_service import PROJECT_STATUSES
from app.services.support_identity import SupportIdentity, support_session_deadline
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    ALL_PERMISSIONS,
    BUSINESS_ROLE_LABELS,
    BUSINESS_ROLES,
    HR_PERMISSIONS,
    ROLE_LABELS,
    permissions_for_role,
)
from app.utils.security import utc_now
from app.utils.time import business_today

_WORKFORCE_SUPPRESSION_THRESHOLD = 5
_OVERSIGHT_RATE_LIMIT = 30
_QUERY_TIMEOUT_SECONDS = 5.0
OPEN_MATERIAL_REQUEST_STATUSES: tuple[str, ...] = (
    "requested",
    "submitted",
    "approved",
    "partially_reserved",
    "reserved",
    "partially_issued",
    "partially_fulfilled",
)
ACTIONABLE_PENDING_APPROVAL_STATUSES: tuple[str, ...] = ("pending", "delegated")


def _unavailable_metric(
    key: str, label: str, source: str, note: str | None = None
) -> OversightMetric:
    return OversightMetric(
        key=key, label=label, value=None, state="unavailable", source=source, note=note
    )


def _metric(
    key: str,
    label: str,
    value: int | str | None,
    source: str,
    *,
    state: MetricState = "observed",
    note: str | None = None,
) -> OversightMetric:
    return OversightMetric(key=key, label=label, value=value, state=state, source=source, note=note)


def _progress_band(progress: object) -> str:
    try:
        numeric = float(str(progress))
    except (TypeError, ValueError):
        return "unknown"
    if numeric <= 0:
        return "0%"
    if numeric < 25:
        return "1-24%"
    if numeric < 50:
        return "25-49%"
    if numeric < 75:
        return "50-74%"
    if numeric < 100:
        return "75-99%"
    return "100%"


def suppress_small_cell_buckets(
    raw_counts: dict[str, int], *, threshold: int = _WORKFORCE_SUPPRESSION_THRESHOLD
) -> tuple[int | None, MetricState, dict[str, tuple[int | None, MetricState]]]:
    """Suppress 1..threshold-1 counts and protect against single-complement inference."""
    total = sum(raw_counts.values())
    buckets: dict[str, tuple[int | None, MetricState]] = {}
    suppressed_keys: list[str] = []
    for key, count in raw_counts.items():
        if 0 < count < threshold:
            buckets[key] = (None, "suppressed")
            suppressed_keys.append(key)
        else:
            buckets[key] = (count, "observed")
    if 0 < total < threshold:
        return None, "suppressed", buckets
    if len(suppressed_keys) == 1:
        # Suppressing the complementary total prevents total - sum(visible) reconstruction.
        return None, "suppressed", buckets
    return total, "observed", buckets


async def _authorize_operator(
    session: AsyncSession,
    token: str | None,
    capability: str,
    *,
    case_id: UUID | None = None,
    project_id: UUID | None = None,
) -> tuple[UUID, UUID, list[UUID] | None]:
    operator, active = await SupportIdentity(session).current(token)
    grant = await session.get(
        SupportOperatorGrant, (operator.id, capability), with_for_update=True
    )
    if grant is None:
        raise PermissionDeniedException(capability)
    scoped_projects: list[UUID] | None = None
    if project_id is not None and case_id is None:
        raise NotFoundException("Support scope")
    if case_id is not None:
        case = await session.get(SupportCase, case_id, with_for_update=True)
        member = await session.get(SupportCaseMember, (case_id, operator.id), with_for_update=True)
        if case is None or member is None:
            raise NotFoundException("Support case")
        if project_id is not None:
            linked = await session.get(SupportCaseProject, (case_id, project_id))
            if linked is None:
                raise NotFoundException("Support project")
            scoped_projects = [project_id]
        else:
            scoped_projects = list(
                await session.scalars(
                    select(SupportCaseProject.project_id)
                    .where(SupportCaseProject.case_id == case_id)
                    .order_by(SupportCaseProject.project_id)
                    .limit(100)
                )
            )
    return operator.id, active.id, scoped_projects


async def execute_oversight_read[T](
    session: AsyncSession,
    token: str | None,
    *,
    capability: str,
    surface: str,
    request_id: str,
    query_fn: Callable[[AsyncSession, datetime, list[UUID] | None], Awaitable[T]],
    degraded_fn: Callable[[datetime], T],
    case_id: UUID | None = None,
    project_id: UUID | None = None,
    timeout_seconds: float = _QUERY_TIMEOUT_SECONDS,
) -> T:
    """Authorize, audit, timeout-bound, re-verify revocation, and return an oversight payload."""
    operator_id, _, scoped_projects = await _authorize_operator(
        session, token, capability, case_id=case_id, project_id=project_id
    )
    now = utc_now()
    recent = await session.scalar(
        select(func.count())
        .select_from(SupportOversightEvent)
        .where(
            SupportOversightEvent.operator_id == operator_id,
            SupportOversightEvent.action == "requested",
            SupportOversightEvent.occurred_at > now - timedelta(minutes=1),
        )
    )
    if recent is not None and recent >= _OVERSIGHT_RATE_LIMIT:
        raise AppException(
            "Wait before reading more oversight metrics.",
            status_code=429,
            error_code="SUPPORT_OVERSIGHT_RATE_LIMIT",
        )
    session.add(
        SupportOversightEvent(
            id=uuid4(),
            operator_id=operator_id,
            surface=surface,
            action="requested",
            case_id=case_id,
            request_id=request_id,
            occurred_at=now,
        )
    )
    await session.commit()

    try:
        async with asyncio.timeout(timeout_seconds):
            result = await query_fn(session, now, scoped_projects)
    except (TimeoutError, SQLAlchemyError):
        await session.rollback()
        result = degraded_fn(now)

    session.expire_all()
    operator, active = await SupportIdentity(session).current(token)
    grant = await session.get(
        SupportOperatorGrant, (operator.id, capability), with_for_update=True
    )
    if grant is None:
        raise PermissionDeniedException(capability)
    if case_id is not None:
        member = await session.get(SupportCaseMember, (case_id, operator.id), with_for_update=True)
        if member is None:
            raise NotFoundException("Support case")
    check_now = utc_now()
    if support_session_deadline(active) <= check_now:
        raise AppException(
            "Support session expired.", status_code=401, error_code="SUPPORT_AUTH_REQUIRED"
        )
    session.add(
        SupportOversightEvent(
            id=uuid4(),
            operator_id=operator.id,
            surface=surface,
            action="returned",
            case_id=case_id,
            request_id=request_id,
            occurred_at=check_now,
        )
    )
    active.last_seen_at = check_now
    await session.commit()
    return result


def _scope(case_id: UUID | None = None, project_id: UUID | None = None) -> OversightScope:
    if project_id is not None and case_id is not None:
        return OversightScope(kind="case_project_scope", case_id=case_id, project_id=project_id)
    if case_id is not None:
        return OversightScope(kind="case_scope", case_id=case_id)
    return OversightScope(kind="approved_company_aggregate")


async def read_company_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportCompanyOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportCompanyOverviewRead:
        today = business_today()
        active_projects = int(
            await db.scalar(
                select(func.count())
                .select_from(Project)
                .where(Project.status == "active", Project.deleted_at.is_(None))
            )
            or 0
        )
        total_projects = int(
            await db.scalar(
                select(func.count()).select_from(Project).where(Project.deleted_at.is_(None))
            )
            or 0
        )
        open_approvals = int(
            await db.scalar(
                select(func.count())
                .select_from(Approval)
                .where(
                    Approval.status.in_(ACTIONABLE_PENDING_APPROVAL_STATUSES),
                    Approval.deleted_at.is_(None),
                )
            )
            or 0
        )
        overdue_approvals = int(
            await db.scalar(
                select(func.count())
                .select_from(Approval)
                .where(
                    Approval.status.in_(ACTIONABLE_PENDING_APPROVAL_STATUSES),
                    Approval.due_at < now,
                    Approval.deleted_at.is_(None),
                )
            )
            or 0
        )
        open_material_requests = int(
            await db.scalar(
                select(func.count())
                .select_from(MaterialRequest)
                .where(
                    MaterialRequest.status.in_(OPEN_MATERIAL_REQUEST_STATUSES),
                    MaterialRequest.deleted_at.is_(None),
                )
            )
            or 0
        )
        pending_documents = int(
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.status == "pending_approval", Document.deleted_at.is_(None))
            )
            or 0
        )
        open_support_cases = int(
            await db.scalar(
                select(func.count())
                .select_from(SupportCase)
                .where(SupportCase.status.in_(("open", "investigating")))
            )
            or 0
        )
        raw_workforce = int(
            await db.scalar(
                select(func.count())
                .select_from(HrEmployee)
                .where(
                    HrEmployee.employment_status.in_(("active", "on_probation")),
                    HrEmployee.deleted_at.is_(None),
                )
            )
            or 0
        )
        workforce_val: int | None
        workforce_state: MetricState
        if 0 < raw_workforce < _WORKFORCE_SUPPRESSION_THRESHOLD:
            workforce_val, workforce_state = None, "suppressed"
        else:
            workforce_val, workforce_state = raw_workforce, "observed"
        expiring_tds = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(
                    Supplier.is_active.is_(True),
                    Supplier.deleted_at.is_(None),
                    Supplier.tds_expiry_date.is_not(None),
                    Supplier.tds_expiry_date <= today + timedelta(days=30),
                )
            )
            or 0
        )
        return SupportCompanyOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            metrics=[
                _metric("active_projects", "Active projects", active_projects, "projects"),
                _metric("total_projects", "Total projects", total_projects, "projects"),
                _metric("open_approvals", "Pending approvals", open_approvals, "approvals"),
                _metric("overdue_approvals", "Overdue approvals", overdue_approvals, "approvals"),
                _metric(
                    "open_material_requests",
                    "Open material requests",
                    open_material_requests,
                    "material_requests",
                ),
                _metric(
                    "pending_documents",
                    "Documents pending approval",
                    pending_documents,
                    "documents",
                ),
                _metric(
                    "expiring_supplier_tds",
                    "Active suppliers with TDS expiring in 30d",
                    expiring_tds,
                    "suppliers",
                ),
                _metric(
                    "active_workforce",
                    "Active/probation workforce count",
                    workforce_val,
                    "hr_employees",
                    state=workforce_state,
                    note=(
                        "Suppressed below privacy threshold (5)."
                        if workforce_state == "suppressed"
                        else None
                    ),
                ),
                _metric(
                    "open_support_cases",
                    "Active support cases",
                    open_support_cases,
                    "support_cases",
                ),
            ],
        )

    def degraded(now: datetime) -> SupportCompanyOverviewRead:
        return SupportCompanyOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("company_summary", "Company summary", "database")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.company.read",
        surface="overview_company",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_projects_overview(
    session: AsyncSession,
    token: str | None,
    request_id: str,
    *,
    case_id: UUID | None = None,
    project_id: UUID | None = None,
) -> SupportProjectsOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, scoped_ids: list[UUID] | None
    ) -> SupportProjectsOverviewRead:
        today = business_today()
        proj_filter = [Project.deleted_at.is_(None)]
        ms_filter = [ProjectMilestone.deleted_at.is_(None)]
        task_filter = [ProjectTask.deleted_at.is_(None)]
        if scoped_ids is not None:
            if not scoped_ids:
                return SupportProjectsOverviewRead(
                    observed_at=now,
                    scope=_scope(case_id, project_id),
                    source_status="operational",
                    freshness="current",
                    metrics=[
                        _metric("total_projects", "Scoped projects", 0, "projects"),
                        _metric(
                            "delayed_milestones",
                            "Delayed milestones",
                            0,
                            "project_milestones",
                        ),
                        _metric("delayed_tasks", "Delayed tasks", 0, "project_tasks"),
                    ],
                )
            proj_filter.append(Project.id.in_(scoped_ids))
            ms_filter.append(ProjectMilestone.project_id.in_(scoped_ids))
            task_filter.append(ProjectTask.project_id.in_(scoped_ids))

        rows = (
            await db.execute(
                select(Project.status, func.count().label("cnt"))
                .where(*proj_filter)
                .group_by(Project.status)
            )
        ).all()
        counts_by_status: dict[str, int] = {}
        for row in rows:
            status_key = row.status if row.status in PROJECT_STATUSES else "unknown"
            counts_by_status[status_key] = counts_by_status.get(status_key, 0) + int(row.cnt)
        delayed_milestones = int(
            await db.scalar(
                select(func.count())
                .select_from(ProjectMilestone)
                .where(
                    *ms_filter,
                    ProjectMilestone.status != "completed",
                    ProjectMilestone.planned_end_date.is_not(None),
                    ProjectMilestone.planned_end_date < today,
                )
            )
            or 0
        )
        delayed_tasks = int(
            await db.scalar(
                select(func.count())
                .select_from(ProjectTask)
                .where(
                    *task_filter,
                    ProjectTask.status != "completed",
                    ProjectTask.planned_end_date.is_not(None),
                    ProjectTask.planned_end_date < today,
                )
            )
            or 0
        )
        open_tasks = int(
            await db.scalar(
                select(func.count())
                .select_from(ProjectTask)
                .where(*task_filter, ProjectTask.status != "completed")
            )
            or 0
        )
        case_projects: list[CaseMaskedProjectSummary] = []
        if scoped_ids is not None:
            proj_rows = (
                await db.execute(
                    select(Project.id, Project.status, Project.progress_percentage)
                    .where(*proj_filter)
                    .order_by(Project.id)
                    .limit(100)
                )
            ).all()
            for idx, proj in enumerate(proj_rows, start=1):
                case_projects.append(
                    CaseMaskedProjectSummary(
                        label=f"Project {idx:02d}",
                        status=proj.status if proj.status in PROJECT_STATUSES else "unknown",
                        progress_band=_progress_band(proj.progress_percentage),
                    )
                )
        total = sum(counts_by_status.values())
        return SupportProjectsOverviewRead(
            observed_at=now,
            scope=_scope(case_id, project_id),
            source_status="operational",
            freshness="current",
            metrics=[
                _metric("total_projects", "Projects in scope", total, "projects"),
                _metric(
                    "active_projects",
                    "Active projects",
                    counts_by_status.get("active", 0),
                    "projects",
                ),
                _metric(
                    "delayed_milestones",
                    "Delayed milestones",
                    delayed_milestones,
                    "project_milestones",
                ),
                _metric("delayed_tasks", "Delayed tasks", delayed_tasks, "project_tasks"),
                _metric("open_tasks", "Open tasks", open_tasks, "project_tasks"),
            ],
            by_status=[
                ProjectStatusBucket(status=status, count=counts_by_status[status])
                for status in sorted(counts_by_status)
            ],
            case_projects=case_projects,
        )

    def degraded(now: datetime) -> SupportProjectsOverviewRead:
        return SupportProjectsOverviewRead(
            observed_at=now,
            scope=_scope(case_id, project_id),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("projects_summary", "Projects summary", "projects")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.projects.read",
        surface="overview_projects",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
        case_id=case_id,
        project_id=project_id,
    )


async def read_workforce_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportWorkforceOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportWorkforceOverviewRead:
        status_rows = (
            await db.execute(
                select(HrEmployee.employment_status, func.count().label("cnt"))
                .where(HrEmployee.deleted_at.is_(None))
                .group_by(HrEmployee.employment_status)
            )
        ).all()
        raw_statuses = {row.employment_status: int(row.cnt) for row in status_rows}
        total_val, total_state, suppressed_statuses = suppress_small_cell_buckets(raw_statuses)

        # Primary-project counts masked as non-identifying project labels and small-cell suppressed.
        project_rows = (
            await db.execute(
                select(HrEmployee.primary_project_id, func.count().label("cnt"))
                .where(
                    HrEmployee.deleted_at.is_(None),
                    HrEmployee.primary_project_id.is_not(None),
                    HrEmployee.employment_status.in_(("active", "on_probation")),
                )
                .group_by(HrEmployee.primary_project_id)
                .order_by(HrEmployee.primary_project_id)
                .limit(50)
            )
        ).all()
        raw_proj_counts = {
            f"Project Group {idx:02d}": int(row.cnt)
            for idx, row in enumerate(project_rows, start=1)
        }
        _, _, suppressed_projects = suppress_small_cell_buckets(raw_proj_counts)

        open_onboarding = int(
            await db.scalar(
                select(func.count())
                .select_from(HrOnboardingCase)
                .where(HrOnboardingCase.status != "completed")
            )
            or 0
        )
        approved_payroll_policies = int(
            await db.scalar(
                select(func.count())
                .select_from(HrPayrollPolicy)
                .where(
                    HrPayrollPolicy.is_approved.is_(True),
                    HrPayrollPolicy.approved_by_id.is_not(None),
                    HrPayrollPolicy.second_approved_by_id.is_not(None),
                    HrPayrollPolicy.approved_by_id != HrPayrollPolicy.second_approved_by_id,
                )
            )
            or 0
        )

        metrics = [
            _metric(
                "total_employees",
                "Total non-deleted employee records",
                total_val,
                "hr_employees",
                state=total_state,
                note="Suppressed below privacy threshold or complement risk."
                if total_state == "suppressed"
                else None,
            ),
            _metric(
                "open_onboarding_cases",
                "Open onboarding cases",
                None if 0 < open_onboarding < _WORKFORCE_SUPPRESSION_THRESHOLD else open_onboarding,
                "hr_onboarding_cases",
                state="suppressed"
                if 0 < open_onboarding < _WORKFORCE_SUPPRESSION_THRESHOLD
                else "observed",
            ),
            _metric(
                "payroll_dual_approved_policies",
                "Dual-approved payroll policies",
                approved_payroll_policies,
                "hr_payroll_policies",
                note="Restricted payroll module remains gated to authorized HR/finance roles.",
            ),
            _metric(
                "payroll_access_policy",
                "Support portal payroll data access",
                "blocked",
                "permissions",
            ),
        ]
        return SupportWorkforceOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            metrics=metrics,
            by_status=[
                WorkforceBucket(status=status, count=val, state=state)
                for status, (val, state) in sorted(suppressed_statuses.items())
            ],
            by_project=[
                WorkforceProjectCount(project_label=label, headcount=val, state=state)
                for label, (val, state) in suppressed_projects.items()
            ],
        )

    def degraded(now: datetime) -> SupportWorkforceOverviewRead:
        return SupportWorkforceOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("workforce_summary", "Workforce summary", "hr_employees")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.workforce.read",
        surface="overview_workforce",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_inventory_overview(
    session: AsyncSession,
    token: str | None,
    request_id: str,
    *,
    case_id: UUID | None = None,
    project_id: UUID | None = None,
) -> SupportInventoryOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, scoped_ids: list[UUID] | None
    ) -> SupportInventoryOverviewRead:
        loc_filter = [StorageLocation.deleted_at.is_(None), StorageLocation.is_active.is_(True)]
        req_filter = [MaterialRequest.deleted_at.is_(None)]
        mov_filter = [
            InventoryMovement.deleted_at.is_(None),
            InventoryMovement.created_at >= now - timedelta(hours=24),
        ]
        if scoped_ids is not None:
            if not scoped_ids:
                return SupportInventoryOverviewRead(
                    observed_at=now,
                    scope=_scope(case_id, project_id),
                    source_status="operational",
                    freshness="current",
                    metrics=[
                        _metric("active_locations", "Active locations", 0, "storage_locations"),
                        _metric("open_material_requests", "Open requests", 0, "material_requests"),
                        _metric(
                            "low_stock_rows",
                            "Low-stock location rows",
                            0,
                            "inventory_location_stock",
                        ),
                    ],
                )
            loc_filter.append(StorageLocation.project_id.in_(scoped_ids))
            req_filter.append(MaterialRequest.project_id.in_(scoped_ids))
            mov_filter.append(InventoryMovement.project_id.in_(scoped_ids))

        active_locations = int(
            await db.scalar(select(func.count()).select_from(StorageLocation).where(*loc_filter))
            or 0
        )
        open_requests = int(
            await db.scalar(
                select(func.count())
                .select_from(MaterialRequest)
                .where(
                    *req_filter,
                    MaterialRequest.status.in_(OPEN_MATERIAL_REQUEST_STATUSES),
                )
            )
            or 0
        )
        overdue_requests = int(
            await db.scalar(
                select(func.count())
                .select_from(MaterialRequest)
                .where(
                    *req_filter,
                    MaterialRequest.status.in_(OPEN_MATERIAL_REQUEST_STATUSES),
                    MaterialRequest.created_at < now - timedelta(days=7),
                )
            )
            or 0
        )
        low_stock_query = (
            select(func.count())
            .select_from(InventoryLocationStock)
            .join(InventoryItem, InventoryItem.id == InventoryLocationStock.item_id)
            .join(StorageLocation, StorageLocation.id == InventoryLocationStock.location_id)
            .where(
                InventoryLocationStock.deleted_at.is_(None),
                InventoryItem.deleted_at.is_(None),
                InventoryItem.is_active.is_(True),
                *loc_filter,
                (InventoryLocationStock.on_hand_qty - InventoryLocationStock.reserved_qty)
                <= InventoryItem.minimum_stock,
            )
        )
        low_stock_rows = int(await db.scalar(low_stock_query) or 0)
        recent_movements = int(
            await db.scalar(select(func.count()).select_from(InventoryMovement).where(*mov_filter))
            or 0
        )
        return SupportInventoryOverviewRead(
            observed_at=now,
            scope=_scope(case_id, project_id),
            source_status="operational",
            freshness="current",
            metrics=[
                _metric(
                    "active_locations",
                    "Active storage locations",
                    active_locations,
                    "storage_locations",
                ),
                _metric(
                    "open_material_requests",
                    "Open material requests",
                    open_requests,
                    "material_requests",
                ),
                _metric(
                    "overdue_material_requests",
                    "Requests open > 7 days",
                    overdue_requests,
                    "material_requests",
                ),
                _metric(
                    "low_stock_rows",
                    "Location stock at/below minimum threshold",
                    low_stock_rows,
                    "inventory_location_stock",
                ),
                _metric(
                    "movements_24h",
                    "Stock movements in last 24h",
                    recent_movements,
                    "inventory_movements",
                ),
            ],
        )

    def degraded(now: datetime) -> SupportInventoryOverviewRead:
        return SupportInventoryOverviewRead(
            observed_at=now,
            scope=_scope(case_id, project_id),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("inventory_summary", "Inventory summary", "inventory")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.inventory.read",
        surface="overview_inventory",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
        case_id=case_id,
        project_id=project_id,
    )


async def read_suppliers_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportSuppliersOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportSuppliersOverviewRead:
        today = business_today()
        active_suppliers = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(Supplier.is_active.is_(True), Supplier.deleted_at.is_(None))
            )
            or 0
        )
        inactive_suppliers = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(Supplier.is_active.is_(False), Supplier.deleted_at.is_(None))
            )
            or 0
        )
        tds_expired = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(
                    Supplier.is_active.is_(True),
                    Supplier.deleted_at.is_(None),
                    Supplier.tds_expiry_date.is_not(None),
                    Supplier.tds_expiry_date < today,
                )
            )
            or 0
        )
        tds_expiring_soon = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(
                    Supplier.is_active.is_(True),
                    Supplier.deleted_at.is_(None),
                    Supplier.tds_expiry_date.is_not(None),
                    Supplier.tds_expiry_date >= today,
                    Supplier.tds_expiry_date <= today + timedelta(days=30),
                )
            )
            or 0
        )
        non_compliant = int(
            await db.scalar(
                select(func.count())
                .select_from(Supplier)
                .where(
                    Supplier.is_active.is_(True),
                    Supplier.deleted_at.is_(None),
                    Supplier.compliance_status != "compliant",
                )
            )
            or 0
        )
        return SupportSuppliersOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            metrics=[
                _metric("active_suppliers", "Active suppliers", active_suppliers, "suppliers"),
                _metric(
                    "inactive_suppliers", "Inactive suppliers", inactive_suppliers, "suppliers"
                ),
                _metric(
                    "tds_expired", "Active suppliers with expired TDS", tds_expired, "suppliers"
                ),
                _metric(
                    "tds_expiring_30d",
                    "Active suppliers with TDS expiring in 30d",
                    tds_expiring_soon,
                    "suppliers",
                ),
                _metric(
                    "non_compliant_suppliers",
                    "Active non-compliant suppliers",
                    non_compliant,
                    "suppliers",
                ),
            ],
        )

    def degraded(now: datetime) -> SupportSuppliersOverviewRead:
        return SupportSuppliersOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("suppliers_summary", "Suppliers summary", "suppliers")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.suppliers.read",
        surface="overview_suppliers",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_documents_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportDocumentsOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportDocumentsOverviewRead:
        today = business_today()
        total_docs = int(
            await db.scalar(
                select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
            )
            or 0
        )
        pending_docs = int(
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.status == "pending_approval", Document.deleted_at.is_(None))
            )
            or 0
        )
        expired_docs = int(
            await db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.deleted_at.is_(None),
                    Document.expiry_date.is_not(None),
                    Document.expiry_date < today,
                )
            )
            or 0
        )
        pending_versions = int(
            await db.scalar(
                select(func.count())
                .select_from(DocumentVersion)
                .where(
                    DocumentVersion.status == "pending_approval",
                    DocumentVersion.deleted_at.is_(None),
                )
            )
            or 0
        )
        return SupportDocumentsOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            metrics=[
                _metric("total_documents", "Controlled documents", total_docs, "documents"),
                _metric(
                    "pending_approval_documents",
                    "Documents pending approval",
                    pending_docs,
                    "documents",
                ),
                _metric(
                    "pending_versions",
                    "Document versions awaiting approval",
                    pending_versions,
                    "document_versions",
                ),
                _metric("expired_documents", "Expired documents", expired_docs, "documents"),
            ],
        )

    def degraded(now: datetime) -> SupportDocumentsOverviewRead:
        return SupportDocumentsOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("documents_summary", "Documents summary", "documents")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.documents.read",
        surface="overview_documents",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_finance_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportFinanceOverviewRead:
    settings = get_settings()

    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportFinanceOverviewRead:
        today = business_today()
        status_rows = (
            await db.execute(
                select(Invoice.status, func.count().label("cnt"))
                .where(Invoice.deleted_at.is_(None))
                .group_by(Invoice.status)
            )
        ).all()
        counts = {row.status: int(row.cnt) for row in status_rows}
        overdue_unpaid = int(
            await db.scalar(
                select(func.count())
                .select_from(Invoice)
                .where(
                    Invoice.deleted_at.is_(None),
                    ~Invoice.status.in_(NON_BILLABLE_INVOICE_STATUSES),
                    Invoice.payment_status != "paid",
                    Invoice.due_date < today,
                )
            )
            or 0
        )
        currency_match = (
            "consistent"
            if settings.business_currency == DEFAULT_BUSINESS_CURRENCY
            else "custom_currency_configured"
        )
        return SupportFinanceOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            finance_writes_policy="blocked",
            operating_currency=settings.business_currency,
            metrics=[
                _metric(
                    "submitted_invoices",
                    "Submitted invoices",
                    counts.get("submitted", 0),
                    "invoices",
                ),
                _metric(
                    "approved_invoices",
                    "Approved invoices",
                    counts.get("approved", 0),
                    "invoices",
                ),
                _metric(
                    "rejected_invoices",
                    "Rejected invoices",
                    counts.get("rejected", 0),
                    "invoices",
                ),
                _metric(
                    "overdue_unpaid_invoices",
                    "Overdue unpaid invoices",
                    overdue_unpaid,
                    "invoices",
                ),
                _metric(
                    "currency_reconciliation",
                    "Operating currency posture",
                    currency_match,
                    "business_policy",
                    note="Counts only; invoice values and payee identities are withheld.",
                ),
            ],
        )

    def degraded(now: datetime) -> SupportFinanceOverviewRead:
        return SupportFinanceOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            finance_writes_policy="blocked",
            operating_currency=settings.business_currency,
            metrics=[_unavailable_metric("finance_summary", "Finance summary", "invoices")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.finance.read",
        surface="overview_finance",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def read_approvals_overview(
    session: AsyncSession, token: str | None, request_id: str
) -> SupportApprovalsOverviewRead:
    async def query(
        db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportApprovalsOverviewRead:
        rows = (
            await db.execute(
                select(
                    Approval.request_type,
                    Approval.status,
                    func.count().label("cnt"),
                    func.count()
                    .filter(
                        Approval.status.in_(
                            (*ACTIONABLE_PENDING_APPROVAL_STATUSES, "escalated")
                        ),
                        Approval.due_at < now,
                    )
                    .label("overdue_cnt"),
                    func.count()
                    .filter(
                        Approval.status.in_(ACTIONABLE_PENDING_APPROVAL_STATUSES),
                        or_(Approval.escalated_at.is_not(None), Approval.status == "escalated"),
                    )
                    .label("escalated_cnt"),
                )
                .where(Approval.deleted_at.is_(None))
                .group_by(Approval.request_type, Approval.status)
                .order_by(Approval.request_type)
                .limit(100)
            )
        ).all()
        grouped: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = grouped.setdefault(
                row.request_type, {"pending": 0, "overdue": 0, "escalated": 0, "rejected": 0}
            )
            if row.status in ACTIONABLE_PENDING_APPROVAL_STATUSES:
                bucket["pending"] += int(row.cnt)
                bucket["overdue"] += int(row.overdue_cnt)
                bucket["escalated"] += int(row.escalated_cnt)
            elif row.status == "rejected":
                bucket["rejected"] += int(row.cnt)
            elif row.status == "escalated":
                bucket["escalated"] += int(row.cnt)
                bucket["overdue"] += int(row.overdue_cnt)

        total_pending = sum(item["pending"] for item in grouped.values())
        total_overdue = sum(item["overdue"] for item in grouped.values())
        total_escalated = sum(item["escalated"] for item in grouped.values())
        total_rejected = sum(item["rejected"] for item in grouped.values())
        ordered_types = sorted(grouped)[:25]
        return SupportApprovalsOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="operational",
            freshness="current",
            truncated=len(grouped) > 25,
            metrics=[
                _metric(
                    "pending_approvals",
                    "Pending approvals",
                    total_pending,
                    "approvals",
                    note=(
                        "Counts pending and delegated approvals; "
                        "escalated approvals are tracked separately."
                    ),
                ),
                _metric("overdue_approvals", "Overdue approvals", total_overdue, "approvals"),
                _metric("escalated_approvals", "Escalated approvals", total_escalated, "approvals"),
                _metric("rejected_approvals", "Rejected approvals", total_rejected, "approvals"),
            ],
            by_workflow=[
                ApprovalWorkflowBucket(request_type=req_type, **grouped[req_type])
                for req_type in ordered_types
            ],
        )

    def degraded(now: datetime) -> SupportApprovalsOverviewRead:
        return SupportApprovalsOverviewRead(
            observed_at=now,
            scope=_scope(),
            source_status="unavailable",
            freshness="unknown",
            metrics=[_unavailable_metric("approvals_summary", "Approvals summary", "approvals")],
        )

    return await execute_oversight_read(
        session,
        token,
        capability="overview.approvals.read",
        surface="overview_approvals",
        request_id=request_id,
        query_fn=query,
        degraded_fn=degraded,
    )


async def explain_role_policy(
    session: AsyncSession,
    token: str | None,
    query: SupportPolicyExplainQuery,
    request_id: str,
) -> SupportPolicyExplainRead:
    """Explain pure static permission policy for a canonical role without reading user rows."""
    known_permissions = ALL_PERMISSIONS | HR_PERMISSIONS
    if query.role_key not in ROLE_LABELS or query.permission_key not in known_permissions:
        raise AppException(
            "Specify a known canonical role key and permission key.",
            status_code=422,
            error_code="VALIDATION_ERROR",
        )

    async def run(
        _db: AsyncSession, now: datetime, _scoped: list[UUID] | None
    ) -> SupportPolicyExplainRead:
        is_business = query.role_key in BUSINESS_ROLES
        grants = permissions_for_role(query.role_key)
        allowed = query.permission_key in grants
        role_label = BUSINESS_ROLE_LABELS.get(query.role_key, ROLE_LABELS[query.role_key])
        if not is_business:
            reason = "Reserved legacy role; excluded from business role assignments."
        elif allowed:
            reason = f"Granted explicitly to canonical business role {role_label}."
        else:
            reason = (
                f"Denied: role {role_label} does not hold {query.permission_key}."
            )
        return SupportPolicyExplainRead(
            observed_at=now,
            role_key=query.role_key,
            role_label=role_label,
            permission_key=query.permission_key,
            allowed=allowed,
            reason=reason,
            is_business_role=is_business,
        )

    def degraded(now: datetime) -> SupportPolicyExplainRead:
        raise AppException(
            "Policy evaluation temporarily unavailable.",
            status_code=503,
            error_code="SUPPORT_POLICY_UNAVAILABLE",
        )

    return await execute_oversight_read(
        session,
        token,
        capability="simulation.start",
        surface="policy_explain",
        request_id=request_id,
        query_fn=run,
        degraded_fn=degraded,
        case_id=query.case_id,
    )
