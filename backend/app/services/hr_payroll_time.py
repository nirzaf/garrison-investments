"""Reconcile time and approved leave sources for a restricted payroll handoff."""

import csv
import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import UUID

from sqlalchemy import Date, cast, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrAttendanceCorrection,
    HrAttendanceEntry,
    HrEmployee,
    HrLeaveLedger,
    HrLeaveRequest,
    HrLeaveType,
    HrOvertimeRequest,
    HrPayrollPeriod,
    HrRosterAllocation,
    HrShiftAssignment,
    HrSiteAttendanceSubmission,
    HrTimesheet,
)
from app.models.user import User
from app.schemas.hr import (
    PayrollLeaveInputIssue,
    PayrollLeaveInputPreview,
    PayrollLeaveIssueCode,
    PayrollTimeInputIssue,
    PayrollTimeInputPreview,
    PayrollTimeIssueCode,
)
from app.services.audit_service import AuditService
from app.services.hr_site_eligibility import historical_site_employment
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import PERMISSION_HR_PAYROLL_PREPARE, ensure_permission


async def lock_payroll_input_roster(
    session: AsyncSession,
    period_id: UUID,
    employee_ids: list[UUID],
) -> tuple[HrPayrollPeriod, set[UUID]]:
    period = await session.get(HrPayrollPeriod, period_id)
    if period is None:
        raise NotFoundException("Payroll period")
    start, end = period.period_start, period.period_end
    if not 0 <= (end - start).days < 31:
        raise AppException("Payroll inputs require a period of up to 31 days.", status_code=409)

    # Time and leave writers share the employee row lock. Taking the locks in UUID order
    # makes the subsequent source reads coherent across overlapping previews.
    roster = set(employee_ids)
    found = set(
        await session.scalars(
            select(HrEmployee.id)
            .where(HrEmployee.id.in_(roster), HrEmployee.deleted_at.is_(None))
            .order_by(HrEmployee.id)
            .with_for_update()
        )
    )
    if found != roster:
        raise NotFoundException("Employee in payroll roster")
    return period, roster


async def payroll_time_inputs(
    session: AsyncSession,
    period_id: UUID,
    employee_ids: list[UUID],
    actor: User,
    *,
    expected_csv_sha256: str | None = None,
) -> tuple[PayrollTimeInputPreview, bytes | None]:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    period, roster = await lock_payroll_input_roster(session, period_id, employee_ids)
    if period.status == "closed":
        raise AppException("The payroll period is closed.", status_code=409)
    result, content = await reconcile_payroll_time_inputs(session, period, roster)
    await _record_input_review(session, "time", result, actor, expected_csv_sha256)
    return result, content


async def reconcile_payroll_time_inputs(
    session: AsyncSession,
    period: HrPayrollPeriod,
    roster: set[UUID],
) -> tuple[PayrollTimeInputPreview, bytes | None]:
    start, end = period.period_start, period.period_end
    issues: list[PayrollTimeInputIssue] = []
    locked_by_employee: dict[UUID, list[HrTimesheet]] = defaultdict(list)
    locked = []
    sheets = await session.scalars(
        select(HrTimesheet)
        .where(
            HrTimesheet.employee_id.in_(roster),
            HrTimesheet.period_start <= end,
            HrTimesheet.period_end >= start,
        )
        .order_by(HrTimesheet.employee_id, HrTimesheet.period_start, HrTimesheet.id)
    )
    code: PayrollTimeIssueCode
    for sheet in sheets:
        if sheet.period_start < start or sheet.period_end > end:
            code = "timesheet_crosses_period"
        elif sheet.status != "locked" or sheet.approved_at is None:
            code = "timesheet_not_locked"
        else:
            previous = locked_by_employee[sheet.employee_id]
            if any(other.period_end >= sheet.period_start for other in previous):
                issues.append(
                    PayrollTimeInputIssue(
                        employee_id=sheet.employee_id,
                        record_id=sheet.id,
                        code="overlapping_timesheets",
                    )
                )
            previous.append(sheet)
            locked.append(sheet)
            continue
        issues.append(
            PayrollTimeInputIssue(employee_id=sheet.employee_id, record_id=sheet.id, code=code)
        )

    for employee_id in roster.difference(locked_by_employee):
        issues.append(
            PayrollTimeInputIssue(employee_id=employee_id, code="missing_locked_timesheet")
        )

    def covering_sheet(employee_id: UUID, day: date) -> HrTimesheet | None:
        return next(
            (
                sheet
                for sheet in locked_by_employee.get(employee_id, [])
                if sheet.period_start <= day <= sheet.period_end
            ),
            None,
        )

    days = (
        func.generate_series(cast(start, Date), cast(end, Date), text("interval '1 day'"))
        .table_valued("day")
        .render_derived()
        .lateral()
    )
    day = cast(days.c.day, Date)
    allocations = (
        select(
            HrRosterAllocation.employee_id,
            HrRosterAllocation.project_id,
            HrRosterAllocation.work_date.label("work_date"),
        )
        .where(
            HrRosterAllocation.employee_id.in_(roster),
            HrRosterAllocation.work_date.between(start, end),
            HrRosterAllocation.cancelled_at.is_(None),
        )
        .cte("payroll_allocations")
    )
    obligations = (
        select(allocations)
        .union(
            select(HrShiftAssignment.employee_id, HrShiftAssignment.project_id, day)
            .join(days, text("true"))
            .where(
                HrShiftAssignment.employee_id.in_(roster),
                HrShiftAssignment.project_id.is_not(None),
                HrShiftAssignment.effective_from <= day,
                or_(
                    HrShiftAssignment.effective_to.is_(None), HrShiftAssignment.effective_to >= day
                ),
                ~select(allocations.c.employee_id)
                .where(
                    allocations.c.employee_id == HrShiftAssignment.employee_id,
                    allocations.c.work_date == day,
                )
                .exists(),
            )
        )
        .subquery()
    )
    work_date = obligations.c.work_date
    eligible, unresolved = historical_site_employment(work_date)
    recorded = (
        select(HrAttendanceEntry.id)
        .where(
            HrAttendanceEntry.employee_id == obligations.c.employee_id,
            HrAttendanceEntry.project_id == obligations.c.project_id,
            HrAttendanceEntry.work_date == work_date,
            HrAttendanceEntry.status != "historical",
            HrAttendanceEntry.source == "site",
        )
        .exists()
    )
    affected = await session.execute(
        select(obligations.c.employee_id, obligations.c.project_id, work_date, unresolved)
        .join(HrEmployee, HrEmployee.id == obligations.c.employee_id)
        .where(unresolved | (eligible & ~recorded))
        .order_by(obligations.c.employee_id, work_date, obligations.c.project_id)
    )
    issues.extend(
        PayrollTimeInputIssue(
            employee_id=employee_id,
            project_id=project_id,
            work_date=on_date,
            code="site_employment_eligibility_unresolved" if unknown else "missing_site_attendance",
        )
        for employee_id, project_id, on_date, unknown in affected
    )
    site_overtime: dict[tuple[UUID, date, UUID | None], tuple[UUID, Decimal]] = {}
    attendance = await session.execute(
        select(HrAttendanceEntry, HrSiteAttendanceSubmission)
        .outerjoin(
            HrSiteAttendanceSubmission,
            (HrSiteAttendanceSubmission.entry_id == HrAttendanceEntry.id)
            & (
                HrSiteAttendanceSubmission.submission_revision
                == HrAttendanceEntry.site_submission_revision
            ),
        )
        .where(
            HrAttendanceEntry.employee_id.in_(roster),
            HrAttendanceEntry.work_date.between(start, end),
            HrAttendanceEntry.status != "historical",
        )
    )
    for entry, site_review in attendance:
        site_pending = entry.source == "site" and (
            site_review is None
            or site_review.engineer_decision != "approved"
            or site_review.engineer_decided_at is None
            or site_review.hr_decision != "approved"
            or site_review.hr_decided_at is None
            or site_review.hr_id != entry.approved_by_id
        )
        if entry.status != "approved" or site_pending:
            issues.append(
                PayrollTimeInputIssue(
                    employee_id=entry.employee_id, record_id=entry.id, code="pending_attendance"
                )
            )
        else:
            if site_review is not None and entry.source == "site":
                site_overtime[(entry.employee_id, entry.work_date, entry.project_id)] = (
                    entry.id,
                    Decimal(site_review.requirements["overtime_hours"]),
                )
            if entry.calendar_id is None or entry.scheduled_workday is None:
                issues.append(
                    PayrollTimeInputIssue(
                        employee_id=entry.employee_id,
                        record_id=entry.id,
                        code="attendance_without_schedule",
                    )
                )
            if covering_sheet(entry.employee_id, entry.work_date) is None:
                issues.append(
                    PayrollTimeInputIssue(
                        employee_id=entry.employee_id,
                        record_id=entry.id,
                        code="attendance_without_timesheet",
                    )
                )

    corrections = await session.execute(
        select(HrAttendanceCorrection.employee_id, HrAttendanceCorrection.id).where(
            HrAttendanceCorrection.employee_id.in_(roster),
            HrAttendanceCorrection.work_date.between(start, end),
            HrAttendanceCorrection.status == "submitted",
        )
    )
    issues.extend(
        PayrollTimeInputIssue(
            employee_id=employee_id, record_id=record_id, code="pending_attendance_correction"
        )
        for employee_id, record_id in corrections
    )

    overtime = await session.scalars(
        select(HrOvertimeRequest)
        .where(
            HrOvertimeRequest.employee_id.in_(roster),
            HrOvertimeRequest.work_date.between(start, end),
            HrOvertimeRequest.status.in_(("submitted", "approved")),
        )
        .order_by(HrOvertimeRequest.employee_id, HrOvertimeRequest.work_date, HrOvertimeRequest.id)
    )
    overtime_by_sheet: dict[UUID, Decimal] = defaultdict(Decimal)
    overtime_days: set[tuple[UUID, date]] = set()
    approved_daily_hours: dict[tuple[UUID, date], Decimal] = {}
    issue: PayrollTimeIssueCode
    for request in overtime:
        matched_sheet = covering_sheet(request.employee_id, request.work_date)
        day_key = (request.employee_id, request.work_date)
        if request.status == "submitted":
            issue = "pending_overtime"
        elif day_key in overtime_days:
            issue = "duplicate_approved_overtime"
        elif matched_sheet is None:
            issue = "overtime_without_timesheet"
        elif request.approved_hours is None or request.decided_at is None:
            issue = "overtime_hours_mismatch"
        else:
            overtime_days.add(day_key)
            approved_daily_hours[day_key] = request.approved_hours
            overtime_by_sheet[matched_sheet.id] += request.approved_hours
            continue
        issues.append(
            PayrollTimeInputIssue(employee_id=request.employee_id, record_id=request.id, code=issue)
        )
    for site_key, (record_id, reported_hours) in site_overtime.items():
        if reported_hours != approved_daily_hours.get(site_key[:2], Decimal("0")):
            issues.append(
                PayrollTimeInputIssue(
                    employee_id=site_key[0],
                    record_id=record_id,
                    work_date=site_key[1],
                    project_id=site_key[2],
                    code="site_overtime_mismatch",
                )
            )
    for sheet in locked:
        if sheet.overtime_hours != overtime_by_sheet[sheet.id]:
            issues.append(
                PayrollTimeInputIssue(
                    employee_id=sheet.employee_id,
                    record_id=sheet.id,
                    code="overtime_hours_mismatch",
                )
            )

    result = PayrollTimeInputPreview(
        payroll_period_id=period.id,
        period_start=start,
        period_end=end,
        employee_count=len(roster),
        timesheet_count=len(locked),
        regular_hours=None,
        overtime_hours=None,
        csv_sha256=None,
        issues=sorted(
            issues, key=lambda item: (str(item.employee_id), item.code, str(item.record_id))
        ),
    )
    content = None
    if not result.issues:
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            (
                "payroll_period_id",
                "employee_id",
                "timesheet_id",
                "timesheet_revision",
                "period_start",
                "period_end",
                "regular_hours",
                "overtime_hours",
            )
        )
        for sheet in locked:
            writer.writerow(
                (
                    period.id,
                    sheet.employee_id,
                    sheet.id,
                    sheet.record_revision,
                    sheet.period_start,
                    sheet.period_end,
                    format(sheet.regular_hours, ".2f"),
                    format(sheet.overtime_hours, ".2f"),
                )
            )
        content = output.getvalue().encode("utf-8")
        result.regular_hours = sum((sheet.regular_hours for sheet in locked), Decimal("0.00"))
        result.overtime_hours = sum((sheet.overtime_hours for sheet in locked), Decimal("0.00"))
        result.csv_sha256 = hashlib.sha256(content).hexdigest()

    return result, content


async def payroll_leave_inputs(
    session: AsyncSession,
    period_id: UUID,
    employee_ids: list[UUID],
    actor: User,
    *,
    expected_csv_sha256: str | None = None,
) -> tuple[PayrollLeaveInputPreview, bytes | None]:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    period, roster = await lock_payroll_input_roster(session, period_id, employee_ids)
    result, content = await reconcile_payroll_leave_inputs(session, period, roster)
    await _record_input_review(session, "leave", result, actor, expected_csv_sha256)
    return result, content


async def reconcile_payroll_leave_inputs(
    session: AsyncSession,
    period: HrPayrollPeriod,
    roster: set[UUID],
) -> tuple[PayrollLeaveInputPreview, bytes | None]:
    start, end = period.period_start, period.period_end
    requests = (
        await session.execute(
            select(HrLeaveRequest, HrLeaveType.is_paid)
            .join(HrLeaveType, HrLeaveType.id == HrLeaveRequest.leave_type_id)
            .where(
                HrLeaveRequest.employee_id.in_(roster),
                HrLeaveRequest.start_date <= end,
                HrLeaveRequest.end_date >= start,
                HrLeaveRequest.status.in_(("submitted", "approved", "cancelled")),
            )
            .order_by(HrLeaveRequest.employee_id, HrLeaveRequest.start_date, HrLeaveRequest.id)
        )
    ).all()
    ledger: dict[UUID, list[HrLeaveLedger]] = defaultdict(list)
    if requests:
        for entry in await session.scalars(
            select(HrLeaveLedger)
            .join(HrLeaveRequest, HrLeaveRequest.id == HrLeaveLedger.reference_request_id)
            .where(
                HrLeaveRequest.employee_id.in_(roster),
                HrLeaveRequest.start_date <= end,
                HrLeaveRequest.end_date >= start,
                HrLeaveRequest.status.in_(("approved", "cancelled")),
            )
        ):
            if entry.reference_request_id is not None:
                ledger[entry.reference_request_id].append(entry)

    issues: list[PayrollLeaveInputIssue] = []
    eligible: dict[UUID, list[tuple[HrLeaveRequest, bool, UUID, Decimal, list[date]]]] = (
        defaultdict(list)
    )
    code: PayrollLeaveIssueCode
    for request, paid in requests:
        entries = ledger[request.id]
        if request.status == "submitted":
            code = "pending_leave"
        elif request.status == "cancelled" and not entries:
            continue
        elif (
            request.days_requested <= 0
            or request.start_date > request.end_date
            or (request.status == "approved" and request.decided_at is None)
            or any(
                (entry.employee_id, entry.leave_type_id, entry.leave_year)
                != (request.employee_id, request.leave_type_id, request.start_date.year)
                for entry in entries
            )
            or sorted((entry.entry_type, entry.days_delta) for entry in entries)
            != (
                [("reversal", request.days_requested), ("taken", -request.days_requested)]
                if request.status == "cancelled"
                else [("taken", -request.days_requested)]
            )
        ):
            code = "leave_ledger_mismatch"
        elif request.status == "cancelled":
            continue
        else:
            work_dates = request.scheduled_work_dates
            if work_dates is None:
                included_dates: list[date] = []
                days = request.days_requested
                allocation_issue = request.start_date < start or request.end_date > end
            else:
                unit = Decimal("0.50") if request.is_half_day else Decimal("1.00")
                if (
                    not work_dates
                    or any(
                        day is None or not request.start_date <= day <= request.end_date
                        for day in work_dates
                    )
                    or work_dates != sorted(set(work_dates))
                    or unit * len(work_dates) != request.days_requested
                    or (request.is_half_day and request.start_date != request.end_date)
                ):
                    issues.append(
                        PayrollLeaveInputIssue(
                            employee_id=request.employee_id,
                            request_id=request.id,
                            code="leave_work_dates_mismatch",
                        )
                    )
                    continue
                included_dates = [day for day in work_dates if start <= day <= end]
                days = unit * len(included_dates)
                allocation_issue = False
            if allocation_issue:
                code = "leave_crosses_period"
            elif not days:
                continue
            elif any(
                earlier.end_date >= request.start_date
                for earlier, _, _, _, _ in eligible[request.employee_id]
            ):
                code = "overlapping_leave"
            else:
                eligible[request.employee_id].append(
                    (request, paid, entries[0].id, days, included_dates)
                )
                continue
        issues.append(
            PayrollLeaveInputIssue(
                employee_id=request.employee_id, request_id=request.id, code=code
            )
        )

    result = PayrollLeaveInputPreview(
        payroll_period_id=period.id,
        period_start=start,
        period_end=end,
        employee_count=len(roster),
        approved_request_count=sum(len(rows) for rows in eligible.values()),
        paid_days=None,
        unpaid_days=None,
        csv_sha256=None,
        issues=issues,
    )
    content = None
    if not issues:
        result.paid_days = Decimal("0.00")
        result.unpaid_days = Decimal("0.00")
        output = StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(
            (
                "payroll_period_id",
                "payroll_period_start",
                "payroll_period_end",
                "employee_id",
                "record_status",
                "leave_request_id",
                "request_revision",
                "leave_start",
                "leave_end",
                "paid",
                "days",
                "ledger_entry_id",
                "allocated_work_dates",
            )
        )
        for employee_id in sorted(roster):
            prefix = (period.id, start, end, employee_id)
            if not eligible[employee_id]:
                writer.writerow((*prefix, "no_approved_leave", "", "", "", "", "", "", "", ""))
                continue
            for request, paid, ledger_id, days, included_dates in eligible[employee_id]:
                writer.writerow(
                    (
                        *prefix,
                        "approved",
                        request.id,
                        request.record_revision,
                        request.start_date,
                        request.end_date,
                        "yes" if paid else "no",
                        format(days, ".2f"),
                        ledger_id,
                        " ".join(day.isoformat() for day in included_dates),
                    )
                )
                if paid:
                    result.paid_days += days
                else:
                    result.unpaid_days += days
        content = output.getvalue().encode("utf-8")
        result.csv_sha256 = hashlib.sha256(content).hexdigest()

    return result, content


async def _record_input_review(
    session: AsyncSession,
    source: str,
    result: PayrollTimeInputPreview | PayrollLeaveInputPreview,
    actor: User,
    expected_csv_sha256: str | None,
) -> None:
    if expected_csv_sha256 is not None and result.csv_sha256 != expected_csv_sha256:
        raise AppException(
            f"Preview the current reconciled {source} inputs before downloading.", status_code=409
        )
    event = "downloaded" if expected_csv_sha256 is not None else "previewed"
    await AuditService(session).record(
        action=f"hr.payroll_{source}.{event}",
        user_id=actor.id,
        entity_type="hr_payroll_periods",
        entity_id=result.payroll_period_id,
        new_values={
            "employee_count": result.employee_count,
            "issue_count": len(result.issues),
            "sha256": result.csv_sha256,
        },
    )
    await session.commit()
