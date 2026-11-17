import csv
import hashlib
import json
from io import StringIO

from pydantic import ValidationError
from sqlalchemy import select

from app.models.hr import HrAttendanceEntry, HrEmployee
from app.models.user import User
from app.schemas.hr import (
    AttendanceEntryCreateRequest,
    AttendanceImportPreviewResponse,
    AttendanceImportRowResponse,
)
from app.services.hr_workforce_service import HrWorkforceService
from app.utils.exceptions import AppException

MAX_ATTENDANCE_CSV_BYTES = 256 * 1024
MAX_ATTENDANCE_ROWS = 250
ATTENDANCE_COLUMNS = (
    "employee_code",
    "work_date",
    "attendance_status",
    "worked_hours",
    "check_in_at",
    "check_out_at",
)


def parse_attendance_csv(raw: bytes) -> list[dict[str, str]]:
    if len(raw) > MAX_ATTENDANCE_CSV_BYTES:
        raise AppException("Attendance CSV files are limited to 256 KiB.", status_code=413)
    try:
        text = raw.decode("utf-8-sig")
        if "\x00" in text:
            raise ValueError
        reader = csv.DictReader(StringIO(text, newline=""), strict=True)
        if tuple(reader.fieldnames or ()) != ATTENDANCE_COLUMNS:
            raise AppException("Use the attendance CSV template header.", status_code=422)
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise AppException("Use a well-formed UTF-8 attendance CSV.", status_code=422) from exc
    if not 1 <= len(rows) <= MAX_ATTENDANCE_ROWS:
        raise AppException("Include between 1 and 250 attendance rows.", status_code=422)
    return rows


async def review_attendance_csv(
    service: HrWorkforceService, raw: bytes, actor: User, *, expected_digest: str | None = None
) -> AttendanceImportPreviewResponse:
    rows = parse_attendance_csv(raw)
    codes = {str(row.get("employee_code") or "").strip() for row in rows}
    query = (
        select(HrEmployee)
        .where(HrEmployee.employee_code.in_(codes), HrEmployee.deleted_at.is_(None))
        .order_by(HrEmployee.id)
    )
    if expected_digest is not None:
        query = query.with_for_update().execution_options(populate_existing=True)
    employees = {
        employee.employee_code: employee for employee in await service.session.scalars(query)
    }
    seen = set()
    items = []
    entries: list[HrAttendanceEntry] = []
    bindings = []
    for index, row in enumerate(rows, start=2):
        code = str(row.get("employee_code") or "").strip()
        employee = employees.get(code)
        item = AttendanceImportRowResponse(row=index, employee_code=code[:40] or None)
        items.append(item)
        try:
            if len(row) != len(ATTENDANCE_COLUMNS) or any(value is None for value in row.values()):
                raise AppException(
                    "The row does not match the template column count.", status_code=422
                )
            if employee is None:
                raise AppException("Use an existing employee code.", status_code=422)
            payload = AttendanceEntryCreateRequest.model_validate(
                {
                    "employee_id": employee.id,
                    "project_id": employee.primary_project_id,
                    "source": "import",
                    **{
                        key: (value.strip() or None)
                        for key, value in row.items()
                        if key != "employee_code"
                    },
                }
            )
            item.work_date = payload.work_date
            item.attendance_status = payload.attendance_status
            item.worked_hours = payload.worked_hours
            identity = (employee.id, payload.work_date)
            if identity in seen:
                raise AppException("This file repeats the employee and work date.", status_code=409)
            seen.add(identity)
            entry = await service.prepare_attendance(payload, actor, employee)
            entries.append(entry)
            item.check_in_at = payload.check_in_at
            item.check_out_at = payload.check_out_at
            bindings.append(
                (
                    employee.id,
                    entry.project_id,
                    entry.calendar_id,
                    entry.shift_assignment_id,
                    entry.scheduled_workday,
                    employee.line_manager_reviewer_id,
                    entry.requires_manager_recommendation,
                )
            )
        except ValidationError:
            item.error = "Check the date, attendance status, decimal hours and clock offsets."
        except AppException as exc:
            item.error = exc.message
    if len(entries) != len(items):
        if expected_digest is not None:
            raise AppException(
                "Attendance changed or the file has errors. Preview it again.", status_code=409
            )
        return AttendanceImportPreviewResponse(items=items)
    signature = hashlib.sha256()
    signature.update(raw)
    signature.update(json.dumps(bindings, default=str, separators=(",", ":")).encode())
    digest = signature.hexdigest()
    if expected_digest is not None:
        if expected_digest != digest:
            raise AppException(
                "The file or its attendance scope changed. Preview it again.", status_code=409
            )
        await service.persist_attendance(entries, actor)
        for item, entry in zip(items, entries, strict=True):
            item.entry_id = entry.id
    return AttendanceImportPreviewResponse(items=items, digest=digest)
