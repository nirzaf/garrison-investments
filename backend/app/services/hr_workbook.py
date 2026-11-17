import csv
import posixpath
import re
import zipfile
from collections import Counter
from hashlib import sha256
from io import BytesIO, StringIO
from uuid import UUID
from xml.etree import ElementTree

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HrAccessRequest, HrEmployee, HrEmploymentHistory
from app.models.user import User
from app.schemas.hr import (
    WorkbookApplyItem,
    WorkbookApplyRequest,
    WorkbookApplyResponse,
    WorkbookPreviewResponse,
    WorkbookRowInput,
    WorkbookRowPreview,
)
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException
from app.utils.permissions import VALID_ROLES
from app.utils.security import utc_now

XLSX_NAMESPACE = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
XLSX_RELATIONSHIP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MAX_XLSX_ENTRIES = 1_000
MAX_XLSX_EXPANDED_BYTES = 200 * 1024 * 1024
MAX_XLSX_COLUMNS = 16_384
MAX_XLSX_CELLS = 1_000_000

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MISSING_EMAIL_MARKERS = {"", "need email", "needs email", "tbd", "n/a", "none", "-"}
_MISSING_CONTACT_MARKERS = {"", "tbd", "n/a", "none", "-"}

_HEADER_ALIASES: dict[str, str] = {
    "user name (source)": "user_name",
    "user name": "user_name",
    "user_name": "user_name",
    "name": "user_name",
    "email / sign-in (source)": "email_source",
    "email / sign-in": "email_source",
    "email": "email_source",
    "email_source": "email_source",
    "employee id": "employee_code",
    "employee code": "employee_code",
    "mobile number": "mobile_number",
    "work phone": "mobile_number",
    "portal access required?": "portal_access_required",
    "portal access required": "portal_access_required",
    "portal_access_required": "portal_access_required",
    "role to assign": "role_to_assign",
    "role": "role_to_assign",
    "role_to_assign": "role_to_assign",
    "role description (auto)": "role_description_auto",
    "role_description_auto": "role_description_auto",
    "privileges (auto)": "privileges_auto",
    "privileges_auto": "privileges_auto",
    "access scope / limits (auto)": "access_scope_auto",
    "access_scope_auto": "access_scope_auto",
}


def _normalize_header(raw: str) -> str:
    cleaned = re.sub(r"\s+", " ", (raw or "").strip().lower())
    return _HEADER_ALIASES.get(cleaned, cleaned)


def _xlsx_column_index(cell_reference: str) -> int:
    match = re.match(r"([A-Z]+)", cell_reference)
    if not match:
        return 0
    index = 0
    for character in match.group(1):
        index = index * 26 + ord(character) - ord("A") + 1
        if index > MAX_XLSX_COLUMNS:
            return MAX_XLSX_COLUMNS
    return index - 1


def _xlsx_sheet_path(archive: zipfile.ZipFile) -> str:
    names = set(archive.namelist())
    workbook_path = "xl/workbook.xml"
    relationships_path = "xl/_rels/workbook.xml.rels"
    if workbook_path not in names and "xl/worksheets/sheet1.xml" in names:
        return "xl/worksheets/sheet1.xml"
    if workbook_path in names and relationships_path in names:
        workbook = ElementTree.fromstring(archive.read(workbook_path))
        relationships = ElementTree.fromstring(archive.read(relationships_path))
        targets = {
            relationship.get("Id"): relationship.get("Target", "")
            for relationship in relationships
            if relationship.get("TargetMode") != "External"
            and relationship.get("Type", "").endswith("/worksheet")
        }
        for sheet in workbook.iterfind("x:sheets/x:sheet", XLSX_NAMESPACE):
            target = targets.get(sheet.get(f"{{{XLSX_RELATIONSHIP_NS}}}id"))
            if not target:
                continue
            path = posixpath.normpath(
                target.lstrip("/") if target.startswith("/") else posixpath.join("xl", target)
            )
            if path.startswith("xl/") and path in names:
                return path
    raise AppException(
        "The HR workbook does not contain a readable worksheet.",
        status_code=422,
        error_code="HR_WORKBOOK_SHEET_NOT_FOUND",
    )


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    if cell.get("t") == "inlineStr":
        return "".join(text.text or "" for text in cell.iterfind(".//x:t", XLSX_NAMESPACE))
    value = cell.findtext("x:v", default="", namespaces=XLSX_NAMESPACE)
    if cell.get("t") != "s" or not value:
        return value
    try:
        idx = int(value)
        if 0 <= idx < len(shared_strings):
            return shared_strings[idx]
    except ValueError:
        pass
    return value


def _parse_xlsx_table(content: bytes) -> list[dict[str, str]]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_XLSX_ENTRIES
                or sum(entry.file_size for entry in entries) > MAX_XLSX_EXPANDED_BYTES
            ):
                raise AppException(
                    "Workbook exceeds safe size limits.",
                    status_code=413,
                    error_code="HR_WORKBOOK_TOO_LARGE",
                )
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                ss_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(text.text or "" for text in item.iterfind(".//x:t", XLSX_NAMESPACE))
                    for item in ss_root.iterfind("x:si", XLSX_NAMESPACE)
                ]
            sheet_path = _xlsx_sheet_path(archive)
            root = ElementTree.fromstring(archive.read(sheet_path))
            table: list[list[str]] = []
            cells_read = 0
            for row in root.iterfind(".//x:sheetData/x:row", XLSX_NAMESPACE):
                values: list[str] = []
                for cell in row.iterfind("x:c", XLSX_NAMESPACE):
                    col_idx = _xlsx_column_index(cell.attrib.get("r", ""))
                    if col_idx >= MAX_XLSX_COLUMNS:
                        raise AppException(
                            "Workbook exceeds column limit.",
                            status_code=413,
                            error_code="HR_WORKBOOK_TOO_LARGE",
                        )
                    values.extend([""] * max(0, col_idx - len(values)))
                    values.append(_xlsx_cell_value(cell, shared_strings))
                cells_read += max(1, len(values))
                if cells_read > MAX_XLSX_CELLS:
                    raise AppException(
                        "Workbook exceeds cell limit.",
                        status_code=413,
                        error_code="HR_WORKBOOK_TOO_LARGE",
                    )
                table.append(values)
    except AppException:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, NotImplementedError, RuntimeError) as exc:
        raise AppException(
            "Unable to parse XLSX workbook.",
            status_code=422,
            error_code="HR_WORKBOOK_INVALID_XLSX",
        ) from exc

    if not table:
        return []
    headers = [_normalize_header(h) for h in table[0]]
    return [
        {header: (row[idx].strip() if idx < len(row) else "") for idx, header in enumerate(headers)}
        for row in table[1:]
        if any(cell.strip() for cell in row)
    ]


def _read_workbook_rows(content: bytes) -> list[dict[str, str]]:
    if not content:
        raise AppException("Uploaded workbook is empty.", status_code=422, error_code="EMPTY_FILE")
    if content.startswith(b"PK"):
        return _parse_xlsx_table(content)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppException(
            "CSV workbook must be UTF-8 encoded.",
            status_code=422,
            error_code="HR_WORKBOOK_INVALID_CSV",
        ) from exc
    reader = csv.DictReader(StringIO(text))
    return [
        {_normalize_header(key): (value or "").strip() for key, value in row.items() if key}
        for row in reader
        if any(value.strip() for value in row.values() if isinstance(value, str))
    ]


async def preview_workbook_upload(
    session: AsyncSession,
    content: bytes,
    *,
    explicit_role_overrides: dict[str, str],
) -> WorkbookPreviewResponse:
    source = _read_workbook_rows(content)
    preview = await preview_workbook(
        session,
        [WorkbookRowInput.model_validate(row) for row in source],
        explicit_role_overrides=explicit_role_overrides,
    )
    for row, original in zip(preview.rows, source, strict=True):
        if not row.portal_access_required or row.matched_user_id is not None:
            continue
        for field, label in (("employee_code", "Employee ID"), ("mobile_number", "Mobile Number")):
            if original.get(field, "").casefold() in _MISSING_CONTACT_MARKERS:
                row.issues.append(f"Missing {label} for account onboarding.")
    return preview


def _parse_bool_flag(raw: str) -> bool:
    return (raw or "").strip().lower() in {"yes", "true", "1", "y", "required"}


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [part for part in full_name.strip().split() if part]
    if not parts:
        return "Unknown", "Staff"
    if len(parts) == 1:
        return parts[0], "Staff"
    return parts[0], " ".join(parts[1:])


async def preview_workbook(
    session: AsyncSession,
    rows: list[WorkbookRowInput],
    *,
    explicit_role_overrides: dict[str, str] | None = None,
) -> WorkbookPreviewResponse:
    overrides = {
        k.strip().lower(): v.strip().lower()
        for k, v in (explicit_role_overrides or {}).items()
        if v.strip().lower() in VALID_ROLES
    }

    names = [row.user_name.strip().casefold() for row in rows]
    emails = [
        row.email_source.strip().lower()
        for row in rows
        if _EMAIL_RE.fullmatch(row.email_source.strip())
    ]
    duplicate_names = Counter(
        name
        for name, row in zip(names, rows, strict=True)
        if not _EMAIL_RE.fullmatch(row.email_source.strip())
    )
    duplicate_emails = Counter(emails)
    draft_codes = {_draft_employee_code(None, name) for name in names if name}
    existing_employees = list(
        await session.scalars(
            select(HrEmployee).where(
                HrEmployee.deleted_at.is_(None),
                or_(
                    func.lower(HrEmployee.work_email).in_(emails),
                    HrEmployee.employee_code.in_(draft_codes),
                ),
            )
        )
    )
    employees_by_email = {
        emp.work_email.lower(): emp for emp in existing_employees if emp.work_email
    }
    employees_by_code = {emp.employee_code: emp for emp in existing_employees}
    existing_users = await session.scalars(
        select(User).where(User.deleted_at.is_(None), func.lower(User.email).in_(emails))
    )
    users_by_email = {user.email.lower(): user for user in existing_users}

    previews: list[WorkbookRowPreview] = []
    counts = {
        "ready_employee": 0,
        "ready_access": 0,
        "blocked_email": 0,
        "unmapped_role": 0,
        "already_linked": 0,
    }

    for idx, row in enumerate(rows, start=1):
        name = row.user_name.strip()
        email_raw = row.email_source.strip()
        email_norm = email_raw.lower()
        portal_req = _parse_bool_flag(row.portal_access_required)
        role_raw = row.role_to_assign.strip()
        role_norm = role_raw.lower()

        issues: list[str] = []
        has_valid_email = bool(_EMAIL_RE.fullmatch(email_norm))
        matched_emp = (
            employees_by_email.get(email_norm)
            if has_valid_email
            else employees_by_code.get(_draft_employee_code(None, name))
        )
        matched_user = users_by_email.get(email_norm) if has_valid_email else None
        duplicate = (
            duplicate_emails[email_norm] > 1
            if has_valid_email
            else duplicate_names[name.casefold()] > 1
        )
        if duplicate:
            issues.append("Duplicate workbook identity. Reconcile these rows before import.")

        # Role evaluation: never guess from business title unless explicitly in VALID_ROLES or
        # explicit_role_overrides.
        mapped_role: str | None = None
        if not portal_req:
            role_mapping_status = "not_required"
        elif role_norm in VALID_ROLES:
            role_mapping_status = "valid_portal_role"
            mapped_role = role_norm
        elif role_norm in overrides:
            role_mapping_status = "valid_portal_role"
            mapped_role = overrides[role_norm]
        else:
            role_mapping_status = "unmapped_business_title"
            issues.append(
                f"Business title '{role_raw or 'blank'}' is not a canonical portal role; "
                "provide explicit mapping before user provisioning."
            )

        if not name:
            issues.append("Missing user name.")

        if portal_req and not has_valid_email:
            issues.append(
                f"Email/sign-in '{email_raw or 'blank'}' requires manual clarification "
                "(placeholder or invalid email)."
            )

        can_import_employee = bool(name) and not duplicate
        can_provision_user = False

        if matched_emp and matched_emp.user_id is not None:
            status = "already_linked"
            counts["already_linked"] += 1
        elif not portal_req:
            status = "ready_employee_only_no_portal_access"
            if can_import_employee:
                counts["ready_employee"] += 1
        elif not has_valid_email:
            status = "blocked_missing_email"
            counts["blocked_email"] += 1
            if can_import_employee:
                counts["ready_employee"] += 1
        elif role_mapping_status != "valid_portal_role":
            status = "blocked_unmapped_role"
            counts["unmapped_role"] += 1
            if can_import_employee:
                counts["ready_employee"] += 1
        else:
            status = "ready_for_employee_and_access_request"
            can_provision_user = can_import_employee
            if can_import_employee:
                counts["ready_employee"] += 1
                counts["ready_access"] += 1

        previews.append(
            WorkbookRowPreview(
                row_number=idx,
                user_name=name,
                email_source=email_raw,
                portal_access_required_raw=row.portal_access_required,
                portal_access_required=portal_req,
                role_source=role_raw,
                role_description_auto=row.role_description_auto,
                privileges_auto=row.privileges_auto,
                access_scope_auto=row.access_scope_auto,
                status=status,  # type: ignore[arg-type]
                role_mapping_status=role_mapping_status,  # type: ignore[arg-type]
                mapped_role=mapped_role,
                issues=issues,
                can_import_employee=can_import_employee,
                can_provision_user=can_provision_user,
                matched_employee_id=matched_emp.id if matched_emp else None,
                matched_user_id=matched_user.id if matched_user else None,
            )
        )

    return WorkbookPreviewResponse(
        total_rows=len(previews),
        ready_employee_rows=counts["ready_employee"],
        ready_access_request_rows=counts["ready_access"],
        blocked_missing_email_rows=counts["blocked_email"],
        unmapped_role_rows=counts["unmapped_role"],
        already_linked_rows=counts["already_linked"],
        rows=previews,
    )


def _draft_employee_code(email: str | None, name: str) -> str:
    return f"DRAFT-{sha256((email or name.casefold()).encode()).hexdigest()[:24].upper()}"


async def apply_workbook(
    session: AsyncSession,
    payload: WorkbookApplyRequest,
    actor: User,
) -> WorkbookApplyResponse:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('garrison.hr_workbook'))"))
    preview = await preview_workbook(
        session,
        payload.rows,
        explicit_role_overrides=payload.explicit_role_overrides,
    )

    employees_created = 0
    employees_updated = 0
    access_requests_created = 0
    skipped_rows = 0
    blocked_rows = 0
    items: list[WorkbookApplyItem] = []

    for row in preview.rows:
        if not row.can_import_employee:
            blocked_rows += 1
            items.append(
                WorkbookApplyItem(
                    row_number=row.row_number,
                    user_name=row.user_name,
                    outcome="blocked",
                    message="Resolve missing or duplicate source identity.",
                )
            )
            continue

        if row.status == "blocked_missing_email" and not payload.allow_missing_email_draft:
            blocked_rows += 1
            items.append(
                WorkbookApplyItem(
                    row_number=row.row_number,
                    user_name=row.user_name,
                    outcome="blocked",
                    message="; ".join(row.issues),
                )
            )
            continue

        email_norm = (
            row.email_source.strip().lower()
            if row.email_source.strip().lower() not in _MISSING_EMAIL_MARKERS
            and _EMAIL_RE.match(row.email_source.strip())
            else None
        )

        employee = (
            await session.get(HrEmployee, row.matched_employee_id, with_for_update=True)
            if row.matched_employee_id
            else None
        )

        access_req_id: UUID | None = None
        if employee is None:
            first_name, last_name = _split_name(row.user_name)
            draft_code = _draft_employee_code(email_norm, row.user_name)
            employee = HrEmployee(
                employee_code=draft_code,
                first_name=first_name,
                last_name=last_name,
                full_name=row.user_name,
                work_email=email_norm,
                employment_status="draft",
                employment_category="permanent",
                work_location=None,
                record_revision=1,
                created_by_id=actor.id,
                updated_by_id=actor.id,
            )
            session.add(employee)
            await session.flush()
            session.add(
                HrEmploymentHistory(
                    employee_id=employee.id,
                    change_type="workbook_imported_draft",
                    effective_date=utc_now().date(),
                    previous_snapshot=None,
                    new_snapshot={
                        "employee_code": employee.employee_code,
                        "full_name": employee.full_name,
                        "work_email": employee.work_email,
                        "employment_status": employee.employment_status,
                        "source_title": row.role_source,
                    },
                    reason="Staged via HR workbook reconciliation.",
                    actor_user_id=actor.id,
                )
            )
            employees_created += 1
            outcome = "created_employee"
        else:
            skipped_rows += 1
            outcome = "skipped"

        # Optionally create draft HrAccessRequest for valid mappable portal rows
        if (
            payload.create_access_requests
            and row.can_provision_user
            and row.mapped_role
            and email_norm
            and employee.user_id is None
        ):
            existing_req = await session.scalar(
                select(HrAccessRequest).where(
                    HrAccessRequest.employee_id == employee.id,
                    HrAccessRequest.status.in_(["draft", "submitted", "hr_approved"]),
                )
            )
            if existing_req is None:
                req = HrAccessRequest(
                    employee_id=employee.id,
                    request_type="link_existing" if row.matched_user_id else "provision",
                    requested_role=row.mapped_role,
                    requested_email=email_norm,
                    portal_access_required=True,
                    business_title_source=row.role_source or None,
                    status="draft",
                    justification="Generated from HR access workbook reconciliation.",
                    requested_by_id=actor.id,
                    linked_user_id=row.matched_user_id,
                )
                session.add(req)
                await session.flush()
                access_req_id = req.id
                access_requests_created += 1

        msg_parts = [f"status={row.status}"]
        if row.issues:
            msg_parts.append("; ".join(row.issues))
        items.append(
            WorkbookApplyItem(
                row_number=row.row_number,
                user_name=row.user_name,
                outcome=outcome,  # type: ignore[arg-type]
                employee_id=employee.id,
                access_request_id=access_req_id,
                message=" | ".join(msg_parts),
            )
        )

    await AuditService(session).record(
        action="hr.workbook.applied",
        user_id=actor.id,
        entity_type="hr_employees",
        new_values={
            "rows_sha256": sha256(payload.model_dump_json().encode()).hexdigest(),
            "employees_created": employees_created,
            "employees_updated": employees_updated,
            "access_requests_created": access_requests_created,
            "skipped_rows": skipped_rows,
            "blocked_rows": blocked_rows,
        },
    )
    await session.commit()

    return WorkbookApplyResponse(
        employees_created=employees_created,
        employees_updated=employees_updated,
        access_requests_created=access_requests_created,
        skipped_rows=skipped_rows,
        blocked_rows=blocked_rows,
        items=items,
    )
