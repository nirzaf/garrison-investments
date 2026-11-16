"""Record external settlement evidence without changing payroll or finance records."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HrClearanceStep, HrEmployee, HrOffboardingCase, HrSeparationSettlement
from app.models.user import User
from app.schemas.hr import (
    SeparationSettlementListResponse,
    SeparationSettlementProposal,
    SeparationSettlementResponse,
    SeparationSettlementReview,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_HR_OFFBOARDING_MANAGE,
    PERMISSION_USERS_MANAGE,
    ensure_permission,
    has_permission,
)

FINANCE_AREA = "finance_accounts"
FINANCE_AUTHORITY = (PERMISSION_FINANCIAL_VIEW, PERMISSION_USERS_MANAGE)
NEWEST = (HrSeparationSettlement.created_at.desc(), HrSeparationSettlement.id.desc())


async def _case_and_step(
    session: AsyncSession, case_id: UUID, *, lock: bool
) -> tuple[HrOffboardingCase, HrClearanceStep]:
    query = select(HrOffboardingCase).where(HrOffboardingCase.id == case_id)
    if lock:
        query = query.with_for_update()
    case = await session.scalar(query)
    if case is None:
        raise NotFoundException("Offboarding case")
    step = await session.scalar(
        select(HrClearanceStep).where(
            HrClearanceStep.offboarding_case_id == case.id,
            HrClearanceStep.department_area == FINANCE_AREA,
        )
    )
    if step is None:
        raise NotFoundException("Finance clearance step")
    return case, step


async def _latest(session: AsyncSession, case_id: UUID) -> HrSeparationSettlement | None:
    return await session.scalar(
        select(HrSeparationSettlement)
        .where(HrSeparationSettlement.case_id == case_id)
        .order_by(*NEWEST)
        .limit(1)
    )


def _ensure_finance_permissions(actor: User) -> None:
    for permission in FINANCE_AUTHORITY:
        ensure_permission(actor, permission)


async def _deny_subject(session: AsyncSession, case: HrOffboardingCase, actor: User) -> None:
    linked_user = await session.scalar(
        select(HrEmployee.user_id).where(HrEmployee.id == case.employee_id).with_for_update()
    )
    if linked_user == actor.id:
        raise PermissionDeniedException("settlement on one's own offboarding case")


async def require_settlement_clearance(
    session: AsyncSession, case: HrOffboardingCase, step: HrClearanceStep
) -> None:
    row = await _latest(session, case.id)
    if (
        row is None
        or row.status != "approved"
        or row.outcome not in {"settled", "nothing_due"}
        or step.status != "cleared"
        or step.cleared_by_id != row.reviewed_by_id
        or step.cleared_at != row.reviewed_at
    ):
        raise AppException(
            "Finance must independently approve the final settlement before closure.",
            status_code=409,
            error_code="SEPARATION_SETTLEMENT_REQUIRED",
        )


async def list_separation_settlements(
    session: AsyncSession,
    case_id: UUID,
    actor: User,
    *,
    limit: int,
    offset: int,
    event_id: UUID | None = None,
) -> SeparationSettlementListResponse:
    if not has_permission(actor, PERMISSION_HR_OFFBOARDING_MANAGE) and not all(
        has_permission(actor, permission) for permission in FINANCE_AUTHORITY
    ):
        raise PermissionDeniedException("read separation settlements")
    case, step = await _case_and_step(session, case_id, lock=False)
    latest = await _latest(session, case.id)
    query = select(HrSeparationSettlement).where(HrSeparationSettlement.case_id == case.id)
    if event_id is not None:
        query = query.where(HrSeparationSettlement.id == event_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(*NEWEST).limit(limit).offset(offset))
    return SeparationSettlementListResponse(
        items=[SeparationSettlementResponse.model_validate(row) for row in rows],
        total=total or 0,
        case_closed=case.status == "completed",
        clearance_status=step.status,
        current_record_id=latest.id if latest else None,
    )


async def _audit(session: AsyncSession, row: HrSeparationSettlement, actor: User) -> None:
    await AuditService(session).record(
        action=f"hr.separation_settlement.{row.status}",
        user_id=actor.id,
        entity_type="hr_offboarding_cases",
        entity_id=row.case_id,
        new_values={"settlement_id": str(row.id), "outcome": row.outcome},
    )


async def propose_separation_settlement(
    session: AsyncSession, case_id: UUID, payload: SeparationSettlementProposal, actor: User
) -> HrSeparationSettlement:
    _ensure_finance_permissions(actor)
    case, step = await _case_and_step(session, case_id, lock=True)
    await _deny_subject(session, case, actor)
    prior = await session.get(HrSeparationSettlement, payload.event_id)
    if prior is not None:
        if (prior.case_id, prior.proposed_by_id, prior.outcome, prior.evidence_reference) == (
            case.id,
            actor.id,
            payload.outcome,
            payload.evidence_reference,
        ):
            return prior
        raise AppException("The settlement event ID is already in use.", status_code=409)
    if case.status == "completed":
        raise AppException("The offboarding case is closed.", status_code=409)
    latest = await _latest(session, case.id)
    if (latest.id if latest else None) != payload.expected_record_id:
        raise AppException(
            "Settlement history changed. Refresh before proposing a new outcome.",
            status_code=409,
            error_code="SEPARATION_SETTLEMENT_CONFLICT",
        )
    if latest is not None and latest.status == "proposed":
        raise AppException("Review the current settlement proposal first.", status_code=409)
    created_at = await session.scalar(select(func.clock_timestamp()))
    row = HrSeparationSettlement(
        id=payload.event_id,
        case_id=case.id,
        proposed_by_id=actor.id,
        outcome=payload.outcome,
        evidence_reference=payload.evidence_reference,
        status="proposed",
        created_at=created_at,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppException(
            "The settlement event or evidence reference already exists.", status_code=409
        ) from exc
    step.status = "flagged" if payload.outcome == "outstanding" else "pending"
    step.notes = None
    step.cleared_by_id = None
    step.cleared_at = None
    case.status = "clearance_in_progress"
    await _audit(session, row, actor)
    await session.commit()
    return row


async def review_separation_settlement(
    session: AsyncSession,
    case_id: UUID,
    event_id: UUID,
    payload: SeparationSettlementReview,
    actor: User,
) -> HrSeparationSettlement:
    _ensure_finance_permissions(actor)
    case, step = await _case_and_step(session, case_id, lock=True)
    await _deny_subject(session, case, actor)
    row = await session.get(HrSeparationSettlement, event_id)
    if row is None or row.case_id != case.id:
        raise NotFoundException("Separation settlement proposal")
    if row.proposed_by_id == actor.id:
        raise PermissionDeniedException("independent separation settlement review")
    if (row.status, row.reviewed_by_id, row.review_reference) == (
        payload.decision,
        actor.id,
        payload.evidence_reference,
    ):
        return row
    if case.status == "completed" or row.status != "proposed":
        raise AppException("The settlement proposal is no longer open for review.", status_code=409)
    reviewed_at = await session.scalar(select(func.clock_timestamp()))
    row.status = payload.decision
    row.reviewed_by_id = actor.id
    row.review_reference = payload.evidence_reference
    row.reviewed_at = reviewed_at
    if row.status == "approved" and row.outcome in {"settled", "nothing_due"}:
        step.status = "cleared"
        step.cleared_by_id = actor.id
        step.cleared_at = row.reviewed_at
    else:
        step.status = "flagged"
    await _audit(session, row, actor)
    await session.commit()
    return row
