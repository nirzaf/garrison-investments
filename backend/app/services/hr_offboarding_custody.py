"""Retain clearance evidence from the inventory owner and the IT access authority."""

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrAccessRequest,
    HrClearanceStep,
    HrEmployee,
    HrOffboardingCase,
    HrOffboardingCustody,
)
from app.models.inventory import InventoryMovement
from app.models.user import User
from app.schemas.hr import (
    OffboardingCustodyArea,
    OffboardingCustodyListResponse,
    OffboardingCustodyRequest,
    OffboardingCustodyResponse,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_OFFBOARDING_MANAGE,
    PERMISSION_INVENTORY_MANAGE,
    PERMISSION_USERS_MANAGE,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now

STORE_AREA: Final = "store_inventory"
IT_AREA: Final = "it_admin"
OWNER_PERMISSIONS = {STORE_AREA: PERMISSION_INVENTORY_MANAGE, IT_AREA: PERMISSION_USERS_MANAGE}


async def confirmed_access_revocation(session: AsyncSession, employee: HrEmployee) -> datetime:
    deactivated_at = await session.scalar(
        select(HrAccessRequest.admin_actioned_at)
        .join(User, User.id == HrAccessRequest.linked_user_id)
        .where(
            HrAccessRequest.employee_id == employee.id,
            HrAccessRequest.request_type == "deactivate",
            HrAccessRequest.status == "admin_actioned",
            User.id == employee.user_id,
            User.is_active.is_(False),
        )
        .order_by(HrAccessRequest.admin_actioned_at.desc().nulls_last())
        .limit(1)
    )
    if deactivated_at is None:
        raise AppException(
            "A director must fulfill a deactivation request before IT clearance.",
            status_code=409,
            error_code="ACCESS_REVOCATION_REQUIRED",
        )
    return deactivated_at


async def _clearance_step(session: AsyncSession, case_id: UUID, area: str) -> HrClearanceStep:
    step = await session.scalar(
        select(HrClearanceStep).where(
            HrClearanceStep.offboarding_case_id == case_id, HrClearanceStep.department_area == area
        )
    )
    if step is None:
        raise NotFoundException("Custody clearance step")
    return step


ORDER_NEWEST = (HrOffboardingCustody.recorded_at.desc(), HrOffboardingCustody.id.desc())


def _events(case_id: UUID, area: str) -> Select[HrOffboardingCustody]:
    return select(HrOffboardingCustody).where(
        HrOffboardingCustody.case_id == case_id, HrOffboardingCustody.area == area
    )


async def _outstanding_devices(session: AsyncSession, case_id: UUID) -> int:
    statuses = (
        _events(case_id, IT_AREA)
        .with_only_columns(
            HrOffboardingCustody.kind,
            func.row_number()
            .over(partition_by=HrOffboardingCustody.device_reference, order_by=ORDER_NEWEST)
            .label("device_version"),
        )
        .where(HrOffboardingCustody.device_reference.is_not(None))
        .subquery()
    )
    return int(
        await session.scalar(
            select(func.count()).where(statuses.c.device_version == 1, statuses.c.kind == "flagged")
        )
        or 0
    )


async def _require_devices_resolved(session: AsyncSession, case_id: UUID) -> None:
    if await _outstanding_devices(session, case_id):
        raise AppException(
            "Resolve outstanding IT devices before signing off.",
            status_code=409,
            error_code="IT_DEVICES_OUTSTANDING",
        )


def _return_movements() -> Select[UUID]:
    return select(InventoryMovement.id).where(
        InventoryMovement.movement_type == "return",
        InventoryMovement.quantity > 0,
        InventoryMovement.deleted_at.is_(None),
        InventoryMovement.reference_type == "hr_offboarding_cases",
    )


async def require_custody_clearance(
    session: AsyncSession, case: HrOffboardingCase, step: HrClearanceStep
) -> None:
    area = step.department_area
    last = await session.scalar(_events(case.id, area).order_by(*ORDER_NEWEST).limit(1))
    if (
        last is None
        or last.device_reference is not None
        or last.kind not in {"cleared", "waived"}
        or last.kind != step.status
        or last.recorded_by_id != step.cleared_by_id
        or last.recorded_at != step.cleared_at
    ):
        if area == IT_AREA:
            raise AppException(
                "A director must attest IT handover before offboarding closes.",
                status_code=409,
                error_code="IT_CLEARANCE_REQUIRED",
            )
        raise AppException(
            "The inventory owner must attest store custody before offboarding closes.",
            status_code=409,
            error_code="CUSTODY_CLEARANCE_REQUIRED",
        )
    if area == IT_AREA:
        await _require_devices_resolved(session, case.id)
        return
    linked = await session.scalars(
        select(HrOffboardingCustody.movement_id).where(
            HrOffboardingCustody.case_id == case.id,
            HrOffboardingCustody.movement_id.is_not(None),
        )
    )
    references = set(linked)
    if references:
        valid = await session.scalars(
            _return_movements().where(
                InventoryMovement.id.in_(references),
                InventoryMovement.reference_id == case.id,
            )
        )
        if set(valid) != references:
            raise AppException(
                "A retained stock return no longer matches this case.", status_code=409
            )


async def list_offboarding_custody(
    session: AsyncSession,
    case_id: UUID,
    actor: User,
    *,
    limit: int,
    offset: int,
    event_id: UUID | None = None,
    area: OffboardingCustodyArea = STORE_AREA,
) -> OffboardingCustodyListResponse:
    if not any(
        has_permission(actor, permission)
        for permission in (PERMISSION_HR_OFFBOARDING_MANAGE, OWNER_PERMISSIONS[area])
    ):
        raise PermissionDeniedException("read offboarding custody")
    case = await session.get(HrOffboardingCase, case_id)
    if case is None:
        raise NotFoundException("Offboarding case")
    step = await _clearance_step(session, case_id, area)
    query = _events(case_id, area)
    if event_id is not None:
        query = query.where(HrOffboardingCustody.id == event_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(*ORDER_NEWEST).limit(limit).offset(offset))
    return OffboardingCustodyListResponse(
        items=[OffboardingCustodyResponse.model_validate(row) for row in rows],
        total=total or 0,
        clearance_status=step.status,
        outstanding_devices=await _outstanding_devices(session, case_id) if area == IT_AREA else 0,
        case_closed=case.status == "completed",
    )


async def _check_it_event(
    session: AsyncSession, case: HrOffboardingCase, payload: OffboardingCustodyRequest
) -> None:
    if payload.kind == "cleared":
        await _require_devices_resolved(session, case.id)
        employee = await session.scalar(
            select(HrEmployee)
            .where(HrEmployee.id == case.employee_id, HrEmployee.deleted_at.is_(None))
            .with_for_update()
        )
        if employee is None:
            raise NotFoundException("Employee")
        if employee.user_id:
            case.access_revoked_at = await confirmed_access_revocation(session, employee)
        return

    previous = await session.scalar(
        _events(case.id, IT_AREA)
        .with_only_columns(HrOffboardingCustody.kind)
        .where(HrOffboardingCustody.device_reference == payload.device_reference)
        .order_by(*ORDER_NEWEST)
        .limit(1)
    )
    if previous == payload.kind or (payload.kind == "waived" and previous != "flagged"):
        raise AppException(
            "This device does not allow the requested custody change.", status_code=409
        )


async def record_offboarding_custody(
    session: AsyncSession, case_id: UUID, payload: OffboardingCustodyRequest, actor: User
) -> HrOffboardingCustody:
    ensure_permission(actor, OWNER_PERMISSIONS[payload.area])
    case = await session.scalar(
        select(HrOffboardingCase).where(HrOffboardingCase.id == case_id).with_for_update()
    )
    if case is None:
        raise NotFoundException("Offboarding case")
    prior = await session.get(HrOffboardingCustody, payload.event_id)
    if prior is not None:
        if prior.recorded_by_id == actor.id and (
            prior.case_id,
            prior.area,
            prior.kind,
            prior.movement_id,
            prior.device_reference,
            prior.evidence_reference,
        ) == (
            case_id,
            payload.area,
            payload.kind,
            payload.movement_id,
            payload.device_reference,
            payload.evidence_reference,
        ):
            return prior
        raise AppException("This custody event ID is already in use.", status_code=409)
    if case.status == "completed":
        raise AppException("The offboarding case is closed.", status_code=409)
    step = await _clearance_step(session, case_id, payload.area)
    if payload.movement_id is not None and not await session.scalar(
        _return_movements().where(
            InventoryMovement.id == payload.movement_id,
            InventoryMovement.reference_id == case_id,
        )
    ):
        raise NotFoundException("Stock return linked to this offboarding case")
    if payload.area == IT_AREA:
        await _check_it_event(session, case, payload)
    now = utc_now()
    row = HrOffboardingCustody(
        id=payload.event_id,
        case_id=case_id,
        area=payload.area,
        kind=payload.kind,
        device_reference=payload.device_reference,
        movement_id=payload.movement_id,
        evidence_reference=payload.evidence_reference,
        recorded_by_id=actor.id,
        recorded_at=now,
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AppException(
            "The custody event, evidence reference or return was already recorded.", status_code=409
        ) from exc
    if payload.area == IT_AREA and row.kind != "cleared":
        step.status = "flagged" if await _outstanding_devices(session, case.id) else "pending"
    else:
        step.status = "pending" if row.kind == "returned" else row.kind
    step.notes = None
    if step.status in {"cleared", "waived"}:
        step.cleared_by_id, step.cleared_at = actor.id, now
    else:
        step.cleared_by_id, step.cleared_at = None, None
    case.status = "clearance_in_progress"
    await AuditService(session).record(
        action=f"hr.offboarding_custody.{row.kind}",
        user_id=actor.id,
        entity_type="hr_offboarding_cases",
        entity_id=case_id,
        new_values={
            "event_id": str(row.id),
            "area": row.area,
            "movement_id": str(row.movement_id) if row.movement_id else None,
        },
    )
    await session.commit()
    return row
