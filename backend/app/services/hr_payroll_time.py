"""Read and reconcile locked time sources for a restricted payroll handoff."""

import csv
import hashlib
from collections import defaultdict
from datetime import date
from decimal import Decimal
from io import StringIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import (
    HrAttendanceCorrection,
    HrAttendanceEntry,
    HrEmployee,
    HrOvertimeRequest,
    HrPayrollPeriod,
    HrTimesheet,
)
from app.models.user import User
from app.schemas.hr import PayrollTimeInputIssue, PayrollTimeInputPreview, PayrollTimeIssueCode
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import PERMISSION_HR_PAYROLL_PREPARE, ensure_permission


async def payroll_time_inputs(
    session: AsyncSession,
    period_id: UUID,
    employee_ids: list[UUID],
    actor: User,
    *,
    expected_csv_sha256: str | None = None,
) -> tuple[PayrollTimeInputPreview, bytes | None]:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_PREPARE)
    period = await session.get(HrPayrollPeriod, period_id)
    if period is None:
        raise NotFoundException("Payroll period")
    start, end = period.period_start, period.period_end
    if not 0 <= (end - start).days < 31:
        raise AppException(
            "Time inputs require a payroll period of up to 31 days.", status_code=409
        )

    # Time writers share the employee row lock. Taking the locks in UUID order
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

    attendance = await session.scalars(
        select(HrAttendanceEntry).where(
            HrAttendanceEntry.employee_id.in_(roster),
            HrAttendanceEntry.work_date.between(start, end),
            HrAttendanceEntry.status != "historical",
        )
    )
    for entry in attendance:
        if entry.status != "approved":
            issues.append(
                PayrollTimeInputIssue(
                    employee_id=entry.employee_id, record_id=entry.id, code="pending_attendance"
                )
            )
        else:
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
            overtime_by_sheet[matched_sheet.id] += request.approved_hours
            continue
        issues.append(
            PayrollTimeInputIssue(employee_id=request.employee_id, record_id=request.id, code=issue)
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

    if expected_csv_sha256 is not None and result.csv_sha256 != expected_csv_sha256:
        raise AppException(
            "Preview the current reconciled time inputs before downloading.", status_code=409
        )
    await AuditService(session).record(
        action=(
            "hr.payroll_time.downloaded"
            if expected_csv_sha256 is not None
            else "hr.payroll_time.previewed"
        ),
        user_id=actor.id,
        entity_type="hr_payroll_periods",
        entity_id=period.id,
        new_values={
            "employee_count": len(roster),
            "issue_count": len(issues),
            "sha256": result.csv_sha256,
        },
    )
    await session.commit()
    return result, content
