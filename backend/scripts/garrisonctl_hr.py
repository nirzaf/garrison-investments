"""HR and workforce management commands backed by the portal HR API."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.garrisonctl_access import has_cli_permission, page, query, require_preview_permission
from scripts.garrisonctl_auth import prompt_secret
from scripts.garrisonctl_common import (
    AUTH,
    CONFLICT,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    load_json,
    mode,
    uuid_arg,
    verified,
)

HR = "/api/v1/hr"
MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 60 * 1024 * 1024

PERM_READ = "hr:employees:read"
PERM_MANAGE = "hr:employees:manage"
PERM_SENSITIVE = "hr:employees:sensitive"
PERM_LEAVE_APPROVE = "hr:leave:approve"
PERM_LEAVE_MANAGE = "hr:leave:manage"
PERM_ATTENDANCE = "hr:attendance:record"
PERM_DOCUMENTS = "hr:documents:manage"
PERM_COMPLIANCE = "hr:compliance:manage"
PERM_OFFBOARDING = "hr:offboarding:manage"
PERM_REPORTS = "hr:reports:view"


def _require_any_permission(ctx: Context, *permissions: str) -> None:
    if not any(has_cli_permission(ctx, perm) for perm in permissions):
        raise CLIError("The authenticated account lacks the required HR permission.", AUTH)


def _employees_list(args: argparse.Namespace, ctx: Context) -> Any:
    require_preview_permission(ctx, PERM_READ)
    return ctx.request(
        "GET",
        f"{HR}/employees",
        params=query(args, "search", "employment_status", "department_id", "limit", "offset"),
    )


def _report_summary(args: argparse.Namespace, ctx: Context) -> Any:
    return ctx.request(
        "GET",
        f"{HR}/reports/summary",
        params=query(args, "project_id", "department_id", "date_from", "date_to"),
    )


def _employees_get(args: argparse.Namespace, ctx: Context) -> Any:
    require_preview_permission(ctx, PERM_READ)
    return ctx.request("GET", f"{HR}/employees/{args.employee_id}")


def _employees_create(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    payload: dict[str, Any] = {
        "employee_code": args.employee_code.strip(),
        "first_name": args.first_name.strip(),
        "last_name": args.last_name.strip(),
        "employment_status": args.employment_status,
        "employment_category": args.employment_category,
        "override_headcount": bool(args.override_headcount),
    }
    for field in (
        "work_email",
        "work_phone",
        "department_id",
        "position_id",
        "primary_project_id",
        "manager_employee_id",
        "work_location",
        "join_date",
        "reason",
    ):
        value = getattr(args, field, None)
        if value is not None:
            payload[field] = value
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/employees", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{HR}/employees/{created['id']}"),
        lambda row: row.get("employee_code") == payload["employee_code"],
    )


def _employees_update(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    current = ctx.request("GET", f"{HR}/employees/{args.employee_id}")
    if current.get("record_revision") != args.expected_revision:
        raise CLIError(
            "Employee record revision changed since it was last read.",
            CONFLICT,
        )
    fields: dict[str, Any] = query(
        args,
        "first_name",
        "last_name",
        "preferred_name",
        "work_email",
        "work_phone",
        "employment_category",
        "department_id",
        "position_id",
        "primary_project_id",
        "manager_employee_id",
        "work_location",
        "reason",
    )
    if args.override_headcount:
        fields["override_headcount"] = True
    if not fields:
        raise CLIError("Provide at least one employee field to update.")
    payload = {"expected_revision": args.expected_revision, **fields}
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "employee_id": args.employee_id,
            "expected_revision": args.expected_revision,
            "proposed": fields,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("PATCH", f"{HR}/employees/{args.employee_id}", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{HR}/employees/{args.employee_id}"),
        lambda row: int(row.get("record_revision", 0)) > args.expected_revision,
    )


def _employees_transition(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, "hr:employees:sensitive")
    current = ctx.request("GET", f"{HR}/employees/{args.employee_id}")
    if current.get("record_revision") != args.expected_revision:
        raise CLIError("Employee record revision changed since it was last read.", CONFLICT)
    payload: dict[str, Any] = {
        "expected_revision": args.expected_revision,
        "status": args.status,
        "reason": args.reason.strip(),
    }
    if args.effective_date:
        payload["effective_date"] = args.effective_date
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "employee_id": args.employee_id,
            "current_status": current.get("employment_status"),
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/employees/{args.employee_id}/status", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{HR}/employees/{args.employee_id}"),
        lambda row: row.get("employment_status") == args.status,
    )


def _departments_create(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    payload: dict[str, Any] = {
        "code": args.code.strip(),
        "name": args.name.strip(),
    }
    for field in ("parent_department_id", "project_id", "description"):
        val = getattr(args, field, None)
        if val is not None:
            payload[field] = val
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/departments", json=payload, write=True)
    return Result(created, changed=True)


def _positions_create(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    payload: dict[str, Any] = {
        "code": args.code.strip(),
        "title": args.title.strip(),
        "employment_category": args.employment_category,
        "headcount_limit": args.headcount_limit,
    }
    for field in ("department_id", "grade", "description"):
        val = getattr(args, field, None)
        if val is not None:
            payload[field] = val
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/positions", json=payload, write=True)
    return Result(created, changed=True)


def _access_requests_create(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    payload: dict[str, Any] = {
        "employee_id": args.employee_id,
        "request_type": args.request_type,
        "portal_access_required": not args.no_portal_access,
        "submit_immediately": bool(args.submit_immediately),
    }
    for field in ("requested_role", "requested_email", "business_title_source", "justification"):
        val = getattr(args, field, None)
        if val is not None:
            payload[field] = val
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/access-requests", json=payload, write=True)
    return Result(created, changed=True)


def _access_requests_decide(args: argparse.Namespace, ctx: Context) -> Result:
    _require_any_permission(ctx, PERM_MANAGE, PERM_SENSITIVE, "users:manage")
    rows = ctx.request("GET", f"{HR}/access-requests").get("items", [])
    target = next((row for row in rows if row.get("id") == args.request_id), None)
    if target is None:
        raise CLIError("HR access request was not found.", CONFLICT)
    plan_body = {
        "operation": args.command_name,
        "request_id": args.request_id,
        "current_status": target.get("status"),
        "action": args.action,
        "link_existing_user_id": args.link_existing_user_id,
        "notes": args.notes,
    }
    plan = checked_plan(args, ctx, plan_body, bind_actor=True)
    if args.dry_run:
        return Result(plan, outcome="preview")
    payload: dict[str, Any] = {"action": args.action}
    if args.notes:
        payload["notes"] = args.notes
    if args.link_existing_user_id:
        payload["link_existing_user_id"] = args.link_existing_user_id
    elif args.action == "admin_action" and target.get("request_type") == "provision":
        password = prompt_secret("Temporary password for provisioned portal account: ")
        ctx.secrets.add(password)
        payload["temporary_password"] = password
    updated = ctx.request(
        "POST",
        f"{HR}/access-requests/{args.request_id}/decision",
        json=payload,
        write=True,
    )
    return Result(updated, changed=True)


def _leave_requests_decide(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_APPROVE)
    rows = ctx.request("GET", f"{HR}/leave/requests").get("items", [])
    target = next((row for row in rows if row.get("id") == args.leave_request_id), None)
    if target is None:
        raise CLIError("Leave request was not found.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "leave_request_id": args.leave_request_id,
            "current_status": target.get("status"),
            "record_revision": target.get("record_revision"),
            "manager_recommendation": target.get("manager_recommendation"),
            "decision": args.decision,
            "notes": args.notes,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    payload: dict[str, Any] = {
        "decision": args.decision,
        "expected_revision": target.get("record_revision"),
    }
    if args.notes:
        payload["notes"] = args.notes
    updated = ctx.request(
        "POST",
        f"{HR}/leave/requests/{args.leave_request_id}/decision",
        json=payload,
        write=True,
    )
    return Result(updated, changed=True)


def _offboarding_initiate(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_OFFBOARDING)
    payload: dict[str, Any] = {
        "employee_id": args.employee_id,
        "separation_type": args.separation_type,
        "last_working_date": args.last_working_date,
    }
    if args.notice_date:
        payload["notice_date"] = args.notice_date
    if args.reason:
        payload["reason"] = args.reason
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/offboarding", json=payload, write=True)
    return Result(created, changed=True)


def _offboarding_complete(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_OFFBOARDING)
    rows = ctx.request("GET", f"{HR}/offboarding").get("items", [])
    target = next((row for row in rows if row.get("id") == args.case_id), None)
    if target is None:
        raise CLIError("Offboarding case was not found.", CONFLICT)
    payload: dict[str, Any] = {}
    if args.exit_interview_notes:
        payload["exit_interview_notes"] = args.exit_interview_notes
    if args.rehire_eligible is not None:
        payload["rehire_eligible"] = args.rehire_eligible
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "case_id": args.case_id,
            "current_status": target.get("status"),
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    completed = ctx.request(
        "POST",
        f"{HR}/offboarding/{args.case_id}/complete",
        json=payload,
        write=True,
    )
    return Result(completed, changed=True)


def _workbook_reconcile(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_MANAGE)
    try:
        with args.file.open("rb") as handle:
            content = handle.read(MAX_WORKBOOK_BYTES + 1)
    except OSError:
        raise CLIError("Workbook file could not be read.") from None
    if not content or len(content) > MAX_WORKBOOK_BYTES:
        raise CLIError("Workbook file must be nonempty and at most 16 MiB.")

    overrides: dict[str, str] = {}
    if args.overrides_file:
        raw_overrides = load_json(args.overrides_file)
        if not isinstance(raw_overrides, dict):
            raise CLIError("Overrides file must contain a JSON object of title -> role mappings.")
        overrides = {str(k): str(v) for k, v in raw_overrides.items()}

    form_data: dict[str, str] = {}
    if overrides:
        form_data["explicit_role_overrides_json"] = json.dumps(overrides, ensure_ascii=False)
    preview = ctx.request(
        "POST",
        f"{HR}/imports/workbook-preview",
        files={"file": (args.file.name, content, "application/octet-stream")},
        data=form_data,
    )
    if not isinstance(preview, dict) or not isinstance(preview.get("rows"), list):
        raise CLIError("The API returned an invalid workbook preview.", CONFLICT)

    summary = {
        "total_rows": preview.get("total_rows"),
        "ready_employee_rows": preview.get("ready_employee_rows"),
        "ready_access_request_rows": preview.get("ready_access_request_rows"),
        "blocked_missing_email_rows": preview.get("blocked_missing_email_rows"),
        "unmapped_role_rows": preview.get("unmapped_role_rows"),
        "already_linked_rows": preview.get("already_linked_rows"),
    }
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "file_name": args.file.name,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "explicit_role_overrides": overrides,
            "allow_missing_email_draft": not args.no_missing_email_draft,
            "create_access_requests": not args.no_access_requests,
            "summary": summary,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result({**plan, "preview": preview}, outcome="preview")

    rows_input = [
        {
            "user_name": row.get("user_name", ""),
            "email_source": row.get("email_source", ""),
            "portal_access_required": row.get("portal_access_required_raw", ""),
            "role_to_assign": row.get("role_source", ""),
            "role_description_auto": row.get("role_description_auto", ""),
            "privileges_auto": row.get("privileges_auto", ""),
            "access_scope_auto": row.get("access_scope_auto", ""),
        }
        for row in preview["rows"]
    ]
    applied = ctx.request(
        "POST",
        f"{HR}/imports/workbook-apply",
        json={
            "rows": rows_input,
            "explicit_role_overrides": overrides,
            "allow_missing_email_draft": not args.no_missing_email_draft,
            "create_access_requests": not args.no_access_requests,
        },
        write=True,
    )
    changed = bool(
        applied.get("employees_created", 0)
        or applied.get("employees_updated", 0)
        or applied.get("access_requests_created", 0)
    )
    return Result(applied, changed=changed)


def _link_employee(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, "users:manage")
    payload = {"user_id": args.user_id}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "employee_id": args.employee_id, **payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    linked = ctx.request(
        "POST", f"{HR}/employees/{args.employee_id}/link-account", json=payload, write=True
    )
    return Result(linked, changed=True)


def _submit_leave(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_MANAGE)
    payload = {
        "employee_id": args.employee_id,
        "leave_type_id": args.leave_type_id,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "days_requested": args.days,
        "submit_immediately": True,
    }
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "proposed": payload}, bind_actor=True
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    return Result(
        ctx.request("POST", f"{HR}/leave/requests", json=payload, write=True), changed=True
    )


def _attendance_correction(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    payload = {
        "employee_id": args.employee_id,
        "work_date": args.work_date,
        "requested_status": args.requested_status,
        "requested_worked_hours": args.hours,
        "reason": args.reason,
    }
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "proposed": payload}, bind_actor=True
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    created = ctx.request("POST", f"{HR}/attendance/corrections", json=payload, write=True)
    return Result(created, changed=True)


def _upload_document(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_DOCUMENTS)
    if args.category != "ordinary":
        require_preview_permission(ctx, PERM_SENSITIVE)
    try:
        with args.file.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
    except OSError:
        raise CLIError("Could not open the HR document.") from None
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise CLIError("HR document must be nonempty and no more than 60 MiB.")
    payload = query(args, "title", "category", "employee_id", "document_type")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "proposed": payload,
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    document = ctx.request(
        "POST",
        f"{HR}/documents",
        write=True,
        data=payload,
        files={"file": (args.file.name, content, "application/octet-stream")},
    )
    return Result(document, changed=True)


def register(registry: Registry) -> None:
    p = registry.add("hr employees list", _employees_list, permission=PERM_READ)
    p.add_argument("--search")
    p.add_argument("--status", dest="employment_status")
    p.add_argument("--department-id", type=uuid_arg)
    page(p)

    p = registry.add("hr employees get", _employees_get, permission=PERM_READ)
    p.add_argument("--employee-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr employees create",
        _employees_create,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-code", required=True)
    p.add_argument("--first-name", required=True)
    p.add_argument("--last-name", required=True)
    p.add_argument("--work-email")
    p.add_argument("--work-phone")
    p.add_argument("--employment-status", default="draft")
    p.add_argument("--employment-category", default="permanent")
    p.add_argument("--department-id", type=uuid_arg)
    p.add_argument("--position-id", type=uuid_arg)
    p.add_argument("--primary-project-id", type=uuid_arg)
    p.add_argument("--manager-employee-id", type=uuid_arg)
    p.add_argument("--work-location")
    p.add_argument("--join-date")
    p.add_argument("--override-headcount", action="store_true")
    p.add_argument("--reason")
    mode(p)

    p = registry.add(
        "hr employees update",
        _employees_update,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--first-name")
    p.add_argument("--last-name")
    p.add_argument("--preferred-name")
    p.add_argument("--work-email")
    p.add_argument("--work-phone")
    p.add_argument("--employment-category")
    p.add_argument("--department-id", type=uuid_arg)
    p.add_argument("--position-id", type=uuid_arg)
    p.add_argument("--primary-project-id", type=uuid_arg)
    p.add_argument("--manager-employee-id", type=uuid_arg)
    p.add_argument("--work-location")
    p.add_argument("--override-headcount", action="store_true")
    p.add_argument("--reason")
    mode(p)

    p = registry.add(
        "hr employees transition",
        _employees_transition,
        permission="hr:employees:sensitive",
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--expected-revision", type=int, required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--effective-date")
    mode(p)

    registry.add(
        "hr departments list",
        lambda a, c: c.request("GET", f"{HR}/departments"),
        permission=PERM_READ,
    )
    p = registry.add(
        "hr employees link-account",
        _link_employee,
        permission="users:manage",
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--user-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr departments create",
        _departments_create,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--code", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--parent-department-id", type=uuid_arg)
    p.add_argument("--project-id", type=uuid_arg)
    p.add_argument("--description")
    mode(p)

    registry.add(
        "hr positions list",
        lambda a, c: c.request("GET", f"{HR}/positions"),
        permission=PERM_READ,
    )
    p = registry.add(
        "hr positions create",
        _positions_create,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--code", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--department-id", type=uuid_arg)
    p.add_argument("--grade")
    p.add_argument("--employment-category", default="permanent")
    p.add_argument("--headcount-limit", type=int, default=1)
    p.add_argument("--description")
    mode(p)

    p = registry.add(
        "hr access-requests list",
        lambda a, c: c.request("GET", f"{HR}/access-requests", params=query(a, "request_status")),
        permission=PERM_READ,
    )
    p.add_argument("--status", dest="request_status")

    p = registry.add(
        "hr access-requests create",
        _access_requests_create,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--request-type", required=True)
    p.add_argument("--requested-role")
    p.add_argument("--requested-email")
    p.add_argument("--business-title-source")
    p.add_argument("--justification")
    p.add_argument("--no-portal-access", action="store_true")
    p.add_argument("--submit-immediately", action="store_true")
    mode(p)

    p = registry.add(
        "hr access-requests decide",
        _access_requests_decide,
        permission=f"{PERM_SENSITIVE} or users:manage",
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument(
        "--action",
        required=True,
        choices=["submit", "hr_approve", "admin_action", "reject", "cancel"],
    )
    p.add_argument("--link-existing-user-id", type=uuid_arg)
    p.add_argument("--notes")
    mode(p)

    p = registry.add(
        "hr attendance list",
        lambda a, c: c.request(
            "GET", f"{HR}/attendance", params=query(a, "employee_id", "date_from", "date_to")
        ),
        permission=PERM_ATTENDANCE,
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--date-from")
    p.add_argument("--date-to")

    p = registry.add(
        "hr attendance correction",
        _attendance_correction,
        permission=PERM_ATTENDANCE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--work-date", required=True)
    p.add_argument("--requested-status", required=True)
    p.add_argument("--hours", required=True)
    p.add_argument("--reason", required=True)
    mode(p)

    p = registry.add(
        "hr documents list",
        lambda a, c: c.request(
            "GET", f"{HR}/documents", params=query(a, "employee_id", "category")
        ),
        permission=PERM_DOCUMENTS,
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--category")

    p = registry.add(
        "hr documents upload",
        _upload_document,
        permission=PERM_DOCUMENTS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--document-type", required=True)
    p.add_argument(
        "--category",
        choices=["ordinary", "confidential", "identity", "medical"],
        default="ordinary",
    )
    mode(p)

    registry.add(
        "hr leave policy show",
        lambda a, c: c.request("GET", f"{HR}/leave/policies"),
        permission=PERM_LEAVE_MANAGE,
    )

    p = registry.add(
        "hr leave requests submit",
        _submit_leave,
        permission=PERM_LEAVE_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--leave-type-id", type=uuid_arg, required=True)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--days", required=True)
    mode(p)

    p = registry.add(
        "hr leave balances",
        lambda a, c: c.request(
            "GET", f"{HR}/leave/balances/{a.employee_id}", params=query(a, "leave_year")
        ),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--leave-year", type=int)

    p = registry.add(
        "hr leave requests list",
        lambda a, c: c.request(
            "GET",
            f"{HR}/leave/requests",
            params=query(a, "req_status", "employee_id"),
        ),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--status", dest="req_status")
    p.add_argument("--employee-id", type=uuid_arg)

    p = registry.add(
        "hr leave requests decide",
        _leave_requests_decide,
        permission=PERM_LEAVE_APPROVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--leave-request-id", type=uuid_arg, required=True)
    p.add_argument(
        "--decision", required=True, choices=["submitted", "approved", "rejected", "cancelled"]
    )
    p.add_argument("--notes")
    mode(p)

    p = registry.add(
        "hr compliance expiring",
        lambda a, c: c.request(
            "GET", f"{HR}/compliance/expiring", params={"within_days": a.within_days}
        ),
        permission=PERM_COMPLIANCE,
    )
    p.add_argument("--within-days", type=int, default=30)

    p = registry.add(
        "hr offboarding list",
        lambda a, c: c.request("GET", f"{HR}/offboarding", params=query(a, "employee_id")),
        permission=PERM_OFFBOARDING,
    )
    p.add_argument("--employee-id", type=uuid_arg)

    p = registry.add(
        "hr offboarding initiate",
        _offboarding_initiate,
        permission=PERM_OFFBOARDING,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument(
        "--separation-type",
        required=True,
        choices=["resignation", "termination", "contract_end", "retirement", "mutual"],
    )
    p.add_argument("--last-working-date", required=True)
    p.add_argument("--notice-date")
    p.add_argument("--reason")
    mode(p)

    p = registry.add(
        "hr offboarding complete",
        _offboarding_complete,
        permission=PERM_OFFBOARDING,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--case-id", type=uuid_arg, required=True)
    p.add_argument("--exit-interview-notes")
    p.add_argument("--rehire-eligible", action=argparse.BooleanOptionalAction, default=None)
    mode(p)

    p = registry.add(
        "hr workbook-reconcile",
        _workbook_reconcile,
        permission=PERM_MANAGE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--file", type=Path, required=True)
    p.add_argument("--overrides-file", type=Path)
    p.add_argument("--no-missing-email-draft", action="store_true")
    p.add_argument("--no-access-requests", action="store_true")
    mode(p)

    for command in ("hr summary", "hr reports summary"):
        p = registry.add(command, _report_summary, permission=PERM_REPORTS)
        p.add_argument("--project-id", type=uuid_arg)
        p.add_argument("--department-id", type=uuid_arg)
        p.add_argument("--date-from", help="Inclusive activity start date (YYYY-MM-DD).")
        p.add_argument("--date-to", help="Inclusive activity end date (YYYY-MM-DD).")

    p = registry.add(
        "hr reports sites",
        lambda a, c: c.request("GET", f"{HR}/reports/sites", params=query(a, "offset", "limit")),
        permission=PERM_REPORTS,
    )
    page(p)
