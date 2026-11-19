"""HR and workforce management commands backed by the portal HR API."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from app.schemas.hr import (
    ApplicationCreateRequest,
    ApplicationStageUpdateRequest,
    ApplicationWithdrawalRequest,
    AttendanceCorrectionCreateRequest,
    AttendanceCorrectionDecisionRequest,
    AttendanceEntryCreateRequest,
    AttendanceImportPreviewResponse,
    AttendanceReviewRequest,
    BenefitTypeCreateRequest,
    BenefitTypeListResponse,
    BenefitTypeResponse,
    CandidateCorrespondenceDecisionRequest,
    CandidateCreateRequest,
    CompensationTermCreateRequest,
    CompensationTermDecisionRequest,
    CompensationTermListResponse,
    CompensationTermResponse,
    EmployeeAdvanceDecision,
    EmployeeAdvanceDisbursement,
    EmployeeAdvanceListResponse,
    EmployeeAdvancePayment,
    EmployeeAdvanceRequest,
    EmployeeAdvanceResponse,
    EmployeeBenefitCreateRequest,
    EmployeeBenefitListResponse,
    EmployeeBenefitResponse,
    HrCaseCloseRequest,
    HrCaseCreateRequest,
    HrCaseListResponse,
    HrCaseResponse,
    HrServiceRequestAssignmentRequest,
    HrServiceRequestResolveRequest,
    InterviewCreateRequest,
    InterviewUpdateRequest,
    LeaveDateEvidenceCreate,
    LeaveDateEvidenceDecision,
    OffboardingCustodyRequest,
    OfferCreateRequest,
    OfferDecisionRequest,
    OfferReissueRequest,
    OnboardingCaseCreateRequest,
    OnboardingTaskUpdateRequest,
    OvertimeDecisionRequest,
    OvertimeRequestCreateRequest,
    PayrollCorrectionCreate,
    PayrollCorrectionDecision,
    PayrollPolicyCreateRequest,
    PayrollPolicyDraftUpdateRequest,
    PayrollRunCalculateRequest,
    PayrollSettlementRequest,
    PayrollSnapshotCalculateRequest,
    PerformanceReviewActionRequest,
    PolicyAcknowledgeRequest,
    PolicyDocumentCreateRequest,
    ProbationReviewRequest,
    ReimbursementCreateRequest,
    ReimbursementDecisionRequest,
    ReimbursementOperatorListResponse,
    ReimbursementOperatorResponse,
    ReimbursementPayableResponse,
    RequisitionCreateRequest,
    RequisitionDecisionRequest,
    RosterAllocationCreateRequest,
    RosterCancellationRequest,
    SeparationSettlementProposal,
    SeparationSettlementReview,
    TimesheetCreateRequest,
    TimesheetDecisionRequest,
    TrainingCompletionRequest,
    TrainingCourseCreateRequest,
    TrainingEnrollmentCreateRequest,
    WorkCalendarCreateRequest,
    WorkCalendarDecisionRequest,
    WorkCalendarUpdateRequest,
)
from scripts.garrisonctl_access import has_cli_permission, page, query, require_preview_permission
from scripts.garrisonctl_auth import prompt_secret
from scripts.garrisonctl_common import (
    AUTH,
    CONFLICT,
    FAILED,
    VALIDATION,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    load_json,
    mode,
    read_private_bytes,
    sha256_json,
    uuid_arg,
    verified,
    write_private_bytes,
)

HR = "/api/v1/hr"
MAX_WORKBOOK_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_BYTES = 60 * 1024 * 1024

PERM_READ = "hr:employees:read"
PERM_MANAGE = "hr:employees:manage"
PERM_SENSITIVE = "hr:employees:sensitive"
PERM_REQUESTS = "hr:requests:process"
PERM_LEAVE_APPROVE = "hr:leave:approve"
PERM_LEAVE_MANAGE = "hr:leave:manage"
PERM_POLICY_MANAGE = "hr:policy:manage"
PERM_ATTENDANCE = "hr:attendance:record"
PERM_ATTENDANCE_REVIEW = "hr:attendance:approve"
PERM_DOCUMENTS = "hr:documents:manage"
PERM_COMPLIANCE = "hr:compliance:manage"
PERM_OFFBOARDING = "hr:offboarding:manage"
PERM_INVENTORY = "inventory:manage"
PERM_REPORTS = "hr:reports:view"
PERM_CASES = "hr:cases:restricted"
PERM_REQUESTS_PROCESS = "hr:requests:process"
PERM_PAYROLL_PREPARE = "hr:payroll:prepare"
PERM_PAYROLL_APPROVE = "hr:payroll:approve"
PERM_PAYROLL_SENSITIVE = "hr:payroll:sensitive"
PERM_RECRUITMENT = "hr:recruitment:manage"
PERM_ONBOARDING = "hr:onboarding:manage"
PERM_TRAINING = "hr:training:manage"


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
    path = f"{HR}/leave/requests/{args.leave_request_id}/decision"
    target = ctx.request("GET", path)
    if target["id"] != args.leave_request_id:
        raise CLIError("The response does not match the requested leave record.", CONFLICT)
    payload = {
        "decision": args.decision,
        "expected_revision": target["record_revision"],
        "notes": args.notes,
    }
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
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    actor_id = ctx.identity()["id"]
    ctx.request("POST", path, json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: (
            row["id"] == args.leave_request_id
            and row["status"] == args.decision
            and row["record_revision"] == target["record_revision"] + 1
            and row["decided_by_id"] == actor_id
        ),
    )


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


def _list_offboarding_custody(args: argparse.Namespace, ctx: Context) -> Result:
    owner = "users:manage" if args.area == "it_admin" else PERM_INVENTORY
    _require_any_permission(ctx, PERM_OFFBOARDING, owner)
    return Result(
        ctx.request(
            "GET",
            f"{HR}/offboarding/{args.case_id}/custody",
            params=query(args, "limit", "offset", "event_id", "area"),
        )
    )


def _record_offboarding_custody(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, "users:manage" if args.area == "it_admin" else PERM_INVENTORY)
    try:
        payload = OffboardingCustodyRequest(
            event_id=args.event_id,
            area=args.area,
            device_reference=args.device_reference,
            kind=args.kind,
            movement_id=args.movement_id,
            evidence_reference=args.evidence_reference,
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError(
            "Provide the required movement or device reference and an opaque evidence reference."
        ) from None
    path = f"{HR}/offboarding/{args.case_id}/custody"
    current = ctx.request("GET", path, params={"limit": 1, "area": args.area})
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "case_id": args.case_id,
            "current_status": current["clearance_status"],
            "case_closed": current["case_closed"],
            "event_count": current["total"],
            "outstanding_devices": current["outstanding_devices"],
            "latest_event_id": next((row["id"] for row in current["items"]), None),
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", path, json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path, params={"event_id": args.event_id, "area": args.area})[
            "items"
        ],
        lambda items: items == [saved] and saved["id"] == args.event_id,
    )


def _settlement_path(case_id: str) -> str:
    return f"{HR}/offboarding/{case_id}/settlement"


def _list_separation_settlements(args: argparse.Namespace, ctx: Context) -> Result:
    if not has_cli_permission(ctx, PERM_OFFBOARDING):
        require_preview_permission(ctx, "financial:view")
        require_preview_permission(ctx, "users:manage")
    return Result(
        ctx.request(
            "GET", _settlement_path(args.case_id), params=query(args, "limit", "offset", "event_id")
        )
    )


def _record_separation_settlement(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, "financial:view")
    require_preview_permission(ctx, "users:manage")
    path = _settlement_path(args.case_id)
    is_review = args.command_name.endswith(" review")
    current = ctx.request("GET", path, params={"limit": 1})
    latest = next(iter(current["items"]), None)
    try:
        if is_review:
            if (
                latest is None
                or latest["id"] != args.event_id
                or latest["status"] != "proposed"
                or current["case_closed"]
            ):
                raise CLIError("Select the current open settlement proposal.", CONFLICT)
            if latest["proposed_by_id"] == ctx.identity()["id"]:
                raise CLIError("A different director must review this proposal.", AUTH)
            payload = SeparationSettlementReview(
                decision=args.decision, evidence_reference=args.evidence_reference
            ).model_dump(mode="json")
            write_path = f"{path}/{args.event_id}/review"
        else:
            if current["case_closed"] or (latest is not None and latest["status"] == "proposed"):
                raise CLIError("Resolve the open proposal or select an open case.", CONFLICT)
            payload = SeparationSettlementProposal(
                event_id=args.event_id,
                expected_record_id=current["current_record_id"],
                outcome=args.outcome,
                evidence_reference=args.evidence_reference,
            ).model_dump(mode="json")
            write_path = path
    except ValidationError:
        raise CLIError("Provide a valid outcome and opaque evidence reference.") from None
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "case_id": args.case_id,
            "clearance_status": current["clearance_status"],
            "current_settlement": latest,
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", write_path, json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path, params={"event_id": args.event_id})["items"],
        lambda items: items == [saved] and saved["id"] == args.event_id,
    )


def _record_performance_action(args: argparse.Namespace, ctx: Context) -> Result:
    path = f"{HR}/performance/reviews/{args.review_id}"

    def events_for(review: dict[str, Any]) -> list[dict[str, Any]]:
        if review["id"] != args.review_id:
            raise CLIError(
                "The response does not match the requested performance review.", CONFLICT
            )
        events: list[dict[str, Any]] = review["events"]
        return events

    review = ctx.request("GET", path)
    actor_id = ctx.identity()["id"]
    existing = next((event for event in events_for(review) if event["id"] == args.event_id), None)
    revision = existing["revision"] - 1 if existing else review["revision"]
    try:
        raw = json.loads(read_private_bytes(args.file, max_bytes=24 * 1024))
        if not isinstance(raw, dict) or {"event_id", "expected_revision"} & raw.keys():
            raise ValueError
        payload = PerformanceReviewActionRequest.model_validate(
            {**raw, "event_id": args.event_id, "expected_revision": revision}
        ).model_dump(mode="json")
    except ValueError:
        raise CLIError("Supply valid review action fields in an owner-only JSON file.") from None

    def matches(event: dict[str, Any]) -> bool:
        return (
            event["actor_id"] == actor_id
            and event["revision"] == revision + 1
            and all(event[key] == payload[key] for key in (
                "action", "notes", "rating", "replacement_reviewer_id"
            ))
        )

    def receipt(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "review_id": args.review_id,
            **{key: event[key] for key in ("id", "revision", "action", "occurred_at")},
        }

    if existing and not matches(existing):
        raise CLIError("The performance event ID is already in use.", CONFLICT)
    if not existing and payload["action"] not in review["allowed_actions"]:
        raise CLIError("This action is unavailable at the current review stage.", AUTH)
    if not existing and payload["action"] in {
        "submit_self_review", "submit_manager_review", "calibrate"
    }:
        scale = review["rating_scale"]
        rating = payload["rating"]
        if (scale and rating not in scale) or (not scale and rating is not None):
            raise CLIError("Use an approved cycle rating, or omit it for a narrative assessment.")
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "review_id": args.review_id,
            "event_id": args.event_id,
            "action": payload["action"],
            "expected_revision": revision,
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if existing:
        return Result(receipt(existing))
    ctx.request("POST", f"{path}/actions", json=payload, write=True)
    observed = verified(
        ctx,
        lambda: next(
            (
                event
                for event in events_for(ctx.request("GET", path))
                if event["id"] == args.event_id
            ),
            None,
        ),
        lambda event: event is not None and matches(event),
    )
    return Result(receipt(observed.data), changed=True)


def _create_training_record(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_TRAINING)
    schema = (
        TrainingCourseCreateRequest
        if args.training_resource == "courses"
        else TrainingEnrollmentCreateRequest
    )
    try:
        proposed = schema.model_validate(
            load_json(args.file, max_bytes=16 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply valid training fields in the JSON file.") from None

    path = f"{HR}/training/{args.training_resource}"
    payload = proposed.model_dump(mode="json")
    params = {"employee_id": payload["employee_id"]} if "employee_id" in payload else None
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")

    saved = ctx.request("POST", path, json=payload, write=True)

    def read_record() -> Any:
        rows = ctx.request("GET", path, params=params)["items"]
        return next((row for row in rows if row["id"] == saved["id"]), None)

    def matches(record: Any) -> bool:
        if record is None:
            return False
        try:
            return schema.model_validate({key: record[key] for key in payload}) == proposed
        except (KeyError, ValidationError):
            return False

    return verified(ctx, read_record, matches)


def _update_training_enrollment(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_TRAINING)
    path = f"{HR}/training/enrollments"

    def read_enrollment() -> dict[str, Any]:
        page = ctx.request("GET", path, params={"employee_id": args.employee_id})
        for enrollment in page["items"]:
            if (
                enrollment["id"] == args.enrollment_id
                and enrollment["employee_id"] == args.employee_id
            ):
                return enrollment
        raise CLIError("The enrollment was not found for this employee.", CONFLICT)

    current = read_enrollment()
    if current["status"] not in {"enrolled", "in_progress"}:
        raise CLIError("The training enrollment is closed.", CONFLICT)
    if current["status"] == args.status:
        raise CLIError("The enrollment already has the requested status.", CONFLICT)

    payload = {"status": args.status, "expected_status": current["status"]}
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "employee_id": args.employee_id,
            "enrollment_id": args.enrollment_id,
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("PATCH", f"{path}/{args.enrollment_id}", json=payload, write=True)
    return verified(ctx, read_enrollment, lambda row: row["status"] == args.status)


def _verify_training_completion(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, "hr:training:manage")
    try:
        payload = TrainingCompletionRequest(
            document_id=args.document_id,
            version_number=args.version_number,
            completed_date=args.completed_date,
            score=args.score,
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError(
            "Provide a valid evidence version, completion date and optional score."
        ) from None
    path = f"{HR}/training/enrollments/{args.enrollment_id}/completion"
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "enrollment_id": args.enrollment_id, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    result = ctx.request("POST", path, json=payload, write=True)
    return verified(ctx, lambda: ctx.request("GET", path), lambda row: row == result)


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


def _requisition_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "id",
            "requisition_code",
            "title",
            "status",
            "headcount_requested",
            "employment_category",
            "target_join_date",
            "updated_at",
        )
    }


def _list_requisitions(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    result = ctx.request(
        "GET", f"{HR}/requisitions", params=query(args, "req_status", "code", "limit", "offset")
    )
    return {
        "items": [_requisition_summary(row) for row in result["items"]],
        "total": result["total"],
    }


def _inspect_requisition(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    row = ctx.request("GET", f"{HR}/requisitions/{args.requisition_id}")
    if args.output is not None:
        try:
            write_private_bytes(args.output, (json.dumps(row, ensure_ascii=False) + "\n").encode())
        except OSError:
            raise CLIError("Could not write a new private requisition file.") from None
    return _requisition_summary(row)


def _create_requisition(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        payload = RequisitionCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Supply a valid private requisition JSON file.") from None
    code, title = payload["requisition_code"].strip(), payload["title"].strip()
    if not code or len(title) < 2:
        raise CLIError("Provide a requisition code and a title of at least two characters.")
    payload.update(requisition_code=code, title=title)
    path = f"{HR}/requisitions"
    if ctx.request("GET", path, params={"code": code, "limit": 1})["total"]:
        raise CLIError("This requisition code is already in use.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "requisition_code": code,
            "headcount_requested": payload["headcount_requested"],
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", path, json=payload, write=True)
    result = verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/{saved['id']}"),
        lambda observed: (
            observed["status"] == "draft"
            and observed["id"] == saved["id"]
            and all(observed[key] == value for key, value in payload.items())
        ),
    )
    result.data = _requisition_summary(result.data)
    return result


def _decide_requisition(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        request = RequisitionDecisionRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private requisition decision JSON file.") from None
    if request.status != "submitted":
        require_preview_permission(ctx, PERM_SENSITIVE)
    if request.expected_updated_at is not None:
        raise CLIError("The CLI supplies the requisition precondition.")
    reason = (request.notes or "").strip()
    if request.status == "rejected" and not reason:
        raise CLIError("Rejection requires a reason.")
    if request.status != "rejected" and request.notes is not None:
        raise CLIError("The API records notes only as the rejection reason.")
    payload = request.model_dump(mode="json", exclude_none=True)
    path = f"{HR}/requisitions/{args.requisition_id}"
    current = _requisition_summary(ctx.request("GET", path))
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "requisition": current,
            "status": request.status,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "POST",
        f"{path}/decision",
        json={**payload, "expected_updated_at": current["updated_at"]},
        write=True,
    )
    result = verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda observed: (
            observed["status"] == request.status
            and observed["id"] == args.requisition_id
            and (request.status != "rejected" or observed["rejection_reason"] == reason)
        ),
    )
    result.data = _requisition_summary(result.data)
    return result


def _offer_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "id",
            "offer_code",
            "application_id",
            "status",
            "valid_until",
            "version_number",
            "document_version_id",
            "updated_at",
            "converted_employee_id",
            "supersedes_offer_id",
            "superseded_by_id",
        )
        if key in row
    }


def _offer_record(ctx: Context, offer_id: str) -> dict[str, Any]:
    row = ctx.request("GET", f"{HR}/offers/{offer_id}")
    if not isinstance(row, dict) or row.get("id") != offer_id:
        raise CLIError("The API returned an invalid offer record.", CONFLICT)
    return row


def _offer_status(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    return _offer_summary(_offer_record(ctx, args.offer_id))


def _inspect_offer(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    row = _offer_record(ctx, args.offer_id)
    summary = _offer_summary(row)
    if args.output is not None:
        terms = {
            **summary,
            **{
                key: row.get(key)
                for key in (
                    "proposed_title",
                    "proposed_department_id",
                    "proposed_position_id",
                    "proposed_join_date",
                    "currency",
                    "notes",
                )
            },
        }
        try:
            write_private_bytes(
                args.output, (json.dumps(terms, ensure_ascii=False) + "\n").encode()
            )
        except OSError:
            raise CLIError("Could not write a new private offer file.") from None
    return summary


def _list_offers(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = ctx.request(
        "GET",
        f"{HR}/offers",
        params=query(args, "application_id", "offer_status", "limit", "offset"),
    )
    return {"items": [_offer_summary(row) for row in listing["items"]], "total": listing["total"]}


def _save_offer_draft(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    path = f"{HR}/offers"
    content = read_private_bytes(args.file, max_bytes=64 * 1024)
    prior: dict[str, Any] | None = None
    try:
        if args.offer_id is None:
            draft = OfferCreateRequest.model_validate_json(content, extra="forbid")
            if (
                draft.supersedes_offer_id is not None
                or draft.expected_application_updated_at is not None
            ):
                raise CLIError("Use reissue for replacements. The CLI supplies the precondition.")
            args.application_id = str(draft.application_id)
            source = _application_status(args, ctx)
            if source["stage"] != "evaluation":
                raise CLIError("Complete interviews before drafting an offer.", CONFLICT)
            precondition = {"expected_application_updated_at": source["updated_at"]}
            payload = draft.model_dump(mode="json", exclude_none=True)
        else:
            replacement = OfferReissueRequest.model_validate_json(content, extra="forbid")
            if replacement.expected_updated_at is not None:
                raise CLIError("The CLI supplies the offer precondition.")
            prior = _offer_status(args, ctx)
            if prior["status"] in {"superseded", "withdrawn", "converted"}:
                raise CLIError("This offer cannot be reissued.", CONFLICT)
            source = prior
            precondition = {"expected_updated_at": prior["updated_at"]}
            payload = replacement.model_dump(mode="json", exclude_none=True)
            path = f"{path}/{args.offer_id}/reissue"
    except ValidationError:
        raise CLIError("Supply a valid private offer terms JSON file.") from None
    if "proposed_salary" in payload:
        raise CLIError("Compensation terms cannot be submitted through recruitment offers.")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "source": source,
            "offer_code": payload["offer_code"],
            "valid_until": payload.get("valid_until"),
            "terms_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", path, json={**payload, **precondition}, write=True)

    def readback() -> dict[str, Any]:
        observed = _offer_summary(_offer_record(ctx, saved["id"]))
        if prior is not None:
            old = _offer_status(args, ctx)
            observed["prior_offer"] = {
                key: old[key] for key in ("id", "status", "superseded_by_id")
            }
        return observed

    return verified(
        ctx,
        readback,
        lambda observed: (
            observed["status"] == "draft"
            and observed["offer_code"] == payload["offer_code"].strip()
            and observed["valid_until"] == payload.get("valid_until")
            and observed["version_number"] == saved["version_number"]
            and observed.get("document_version_id") == payload.get("document_version_id")
            and observed["application_id"] == (prior["application_id"] if prior else source["id"])
            and (
                prior is None
                or (
                    observed["supersedes_offer_id"] == prior["id"]
                    and observed["version_number"] > prior["version_number"]
                    and observed["prior_offer"]["status"] == "superseded"
                    and observed["prior_offer"]["superseded_by_id"] == observed["id"]
                )
            )
        ),
    )


def _decide_offer(args: argparse.Namespace, ctx: Context) -> Result:
    offer = _offer_status(args, ctx)
    if offer.get("superseded_by_id") or offer["status"] == "superseded":
        raise CLIError("Review the newest offer version before recording a decision.", CONFLICT)
    try:
        request = OfferDecisionRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private offer decision JSON file.") from None
    if request.status == "approved":
        require_preview_permission(ctx, PERM_SENSITIVE)
    if request.expected_updated_at is not None or request.expected_version_number is not None:
        raise CLIError("The CLI supplies the offer version and update preconditions.")
    payload = request.model_dump(mode="json", exclude_none=True)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "offer": offer,
            "status": request.status,
            "valid_until": payload.get("valid_until", offer.get("valid_until")),
            "decision_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "POST",
        f"{HR}/offers/{args.offer_id}/decision",
        write=True,
        json={
            **payload,
            "expected_version_number": offer["version_number"],
            "expected_updated_at": offer["updated_at"],
        },
    )
    return verified(
        ctx,
        lambda: _offer_status(args, ctx),
        lambda observed: (
            observed["status"] == request.status
            and observed["version_number"] == offer["version_number"]
            and observed["valid_until"] == plan["valid_until"]
        ),
    )


def _convert_offer(args: argparse.Namespace, ctx: Context) -> Result:
    offer = _offer_status(args, ctx)
    if offer.get("status") != "accepted":
        raise CLIError("Only an accepted offer can start onboarding.", CONFLICT)
    payload = {"employee_code": args.employee_code.strip(), "probation_days": args.probation_days}
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "environment": ctx.environment,
            "offer": offer,
            "proposed": payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    case = ctx.request("POST", f"{HR}/offers/{args.offer_id}/convert", json=payload, write=True)
    case_id = case.get("id") if isinstance(case, dict) else None
    employee_id = case.get("employee_id") if isinstance(case, dict) else None
    return verified(
        ctx,
        lambda: {**_offer_status(args, ctx), "onboarding_case_id": case_id},
        lambda saved: (
            bool(case_id)
            and bool(employee_id)
            and saved.get("status") == "converted"
            and saved.get("converted_employee_id") == employee_id
        ),
    )


def _onboarding_path(case_id: str) -> str:
    return f"{HR}/onboarding/{case_id}"


def _onboarding_summary(case: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            key: case[key]
            for key in (
                "id",
                "employee_id",
                "offer_id",
                "status",
                "start_date",
                "probation_end_date",
                "employee_status",
                "employee_revision",
                "employee_category",
                "updated_at",
            )
        },
        "tasks": [
            {
                key: task[key]
                for key in (
                    "id",
                    "code",
                    "status",
                    "assignee_role",
                    "is_mandatory",
                    "updated_at",
                )
            }
            for task in case["tasks"]
        ],
    }


def _list_onboarding(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = ctx.request(
        "GET",
        f"{HR}/onboarding",
        params=query(args, "employee_id", "case_status", "limit", "offset"),
    )
    return {
        "items": [_onboarding_summary(case) for case in listing["items"]],
        "total": listing["total"],
    }


def _inspect_onboarding(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    case = ctx.request("GET", _onboarding_path(args.case_id))
    if args.output is not None:
        _write_recruitment_detail(args.output, case)
    return _onboarding_summary(case)


def _create_onboarding(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ONBOARDING)
    try:
        request = OnboardingCaseCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=8192), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private onboarding JSON file.") from None
    if request.probation_end_date is not None and request.probation_end_date < request.start_date:
        raise CLIError("Probation cannot end before the start date.")
    payload = request.model_dump(mode="json")
    path = f"{HR}/onboarding"
    for status in ("open", "in_progress"):
        if ctx.request(
            "GET",
            path,
            params={"employee_id": payload["employee_id"], "case_status": status, "limit": 1},
        )["total"]:
            raise CLIError("An open onboarding case already exists for this employee.", CONFLICT)
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "case": payload}, bind_actor=True
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", path, json=payload, write=True)
    return verified(
        ctx,
        lambda: _onboarding_summary(ctx.request("GET", _onboarding_path(saved["id"]))),
        lambda case: (
            case["employee_id"] == payload["employee_id"]
            and case["status"] == "open"
            and case["start_date"] == payload["start_date"]
            and case["probation_end_date"] == payload["probation_end_date"]
            and bool(case["tasks"])
            and all(task["status"] == "pending" for task in case["tasks"])
        ),
    )


def _onboarding_task(case: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in case["tasks"]:
        if task["id"] == task_id:
            return task
    raise CLIError("The checklist task is unavailable in this case.", CONFLICT)


def _update_onboarding_task(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ONBOARDING)
    try:
        request = OnboardingTaskUpdateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply valid private checklist update JSON.") from None
    if request.expected_updated_at is not None:
        raise CLIError("The CLI supplies the checklist precondition.")
    if request.status in {"completed", "waived"} and not (request.evidence_notes or "").strip():
        raise CLIError("Checklist evidence is required.")
    path = _onboarding_path(args.case_id)
    current = _onboarding_summary(ctx.request("GET", path))
    if current["status"] == "completed":
        raise CLIError("This onboarding case is already closed.", CONFLICT)
    task = _onboarding_task(current, args.task_id)
    if request.status == "waived" or (
        request.status == "completed"
        and all(
            item["id"] == args.task_id
            or not item["is_mandatory"]
            or item["status"] in {"completed", "waived"}
            for item in current["tasks"]
        )
    ):
        require_preview_permission(ctx, PERM_SENSITIVE)
    payload = request.model_dump(mode="json", exclude={"expected_updated_at"})
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "case": current,
            "task_id": args.task_id,
            "status": request.status,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "PATCH",
        f"{HR}/onboarding/tasks/{args.task_id}",
        write=True,
        json={**payload, "expected_updated_at": task["updated_at"]},
    )
    result = verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda case: (
            case["status"] == saved["status"]
            and any(
                task["id"] == args.task_id
                and task["status"] == request.status
                and task["evidence_notes"] == request.evidence_notes
                for task in case["tasks"]
            )
        ),
    )
    result.data = _onboarding_summary(result.data)
    return result


def _review_probation(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ONBOARDING)
    require_preview_permission(ctx, PERM_SENSITIVE)
    path = _onboarding_path(args.case_id)
    case = _onboarding_summary(ctx.request("GET", path))
    if (
        case["status"] != "completed"
        or case["employee_status"] != "on_probation"
        or not case["probation_end_date"]
        or case["employee_revision"] is None
    ):
        raise CLIError("Select a completed case for an employee on probation.", CONFLICT)
    try:
        body = json.loads(read_private_bytes(args.file, max_bytes=8192))
        if not isinstance(body, dict) or "expected_employee_revision" in body:
            raise ValueError
        request = ProbationReviewRequest.model_validate(
            {**body, "expected_employee_revision": case["employee_revision"]}, extra="forbid"
        )
    except ValueError:
        raise CLIError("Supply valid private probation review JSON.") from None
    if not request.reason.strip():
        raise CLIError("A probation review reason is required.")
    payload = request.model_dump(mode="json")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "case": case,
            "outcome": request.outcome,
            "new_end_date": payload["new_end_date"],
            "confirmed_category": request.confirmed_category,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/probation-review", json=payload, write=True)
    return verified(
        ctx,
        lambda: _onboarding_summary(ctx.request("GET", path)),
        lambda saved: (
            saved["employee_revision"] == case["employee_revision"] + 1
            and saved["employee_status"]
            == ("active" if request.outcome == "confirm" else "on_probation")
            and saved["probation_end_date"]
            == (payload["new_end_date"] or case["probation_end_date"])
            and saved["employee_category"]
            == (request.confirmed_category or case["employee_category"])
        ),
    )


def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: candidate[key]
        for key in ("id", "candidate_code", "full_name", "status", "resume_document_id")
    }


def _list_candidates(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = ctx.request(
        "GET", f"{HR}/candidates", params=query(args, "search", "code", "limit", "offset")
    )
    return {
        "items": [_candidate_summary(row) for row in listing["items"]],
        "total": listing["total"],
    }


def _write_recruitment_detail(output: Path, row: dict[str, Any]) -> None:
    try:
        write_private_bytes(output, (json.dumps(row, ensure_ascii=False) + "\n").encode())
    except OSError:
        raise CLIError("Could not write a new private recruitment file.") from None


def _inspect_candidate(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    row = ctx.request("GET", f"{HR}/candidates/{args.candidate_id}")
    if args.output is not None:
        _write_recruitment_detail(args.output, row)
    return _candidate_summary(row)


def _create_candidate(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        payload = CandidateCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Supply a valid private candidate JSON file.") from None
    code, name = payload["candidate_code"].strip(), payload["full_name"].strip()
    if not code or len(name) < 2:
        raise CLIError("Provide a candidate code and a name of at least two characters.")
    payload.update(candidate_code=code, full_name=name)
    if payload["email"] is not None:
        payload["email"] = payload["email"].lower()
    path = f"{HR}/candidates"
    if ctx.request("GET", path, params={"code": code, "limit": 1})["total"]:
        raise CLIError("This candidate code is already in use.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "candidate_code": code,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", path, json=payload, write=True)
    result = verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/{saved['id']}"),
        lambda observed: (
            observed["id"] == saved["id"] and all(observed[key] == saved[key] for key in payload)
        ),
    )
    result.data = _candidate_summary(result.data)
    return result


def _application_summary(application: dict[str, Any]) -> dict[str, Any]:
    return {
        key: application.get(key)
        for key in (
            "id",
            "stage",
            "updated_at",
            "withdrawn_at",
            "retention_decision",
            "retention_review_on",
            "retention_policy_reference",
        )
    }


def _application_status(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    return _application_summary(ctx.request("GET", f"{HR}/applications/{args.application_id}"))


def _inspect_application(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    row = ctx.request("GET", f"{HR}/applications/{args.application_id}")
    if args.output is not None:
        _write_recruitment_detail(args.output, row)
    return _application_summary(row)


def _list_applications(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = ctx.request(
        "GET",
        f"{HR}/applications",
        params=query(args, "requisition_id", "candidate_id", "stage", "limit", "offset"),
    )
    return {
        "items": [
            {
                **_application_summary(row),
                "requisition_id": row["requisition_id"],
                "candidate_id": row["candidate_id"],
            }
            for row in listing["items"]
        ],
        "total": listing["total"],
    }


def _create_application(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        request = ApplicationCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private application JSON file.") from None
    if request.expected_requisition_updated_at is not None:
        raise CLIError("The CLI supplies the requisition precondition.")
    payload = request.model_dump(mode="json", exclude={"expected_requisition_updated_at"})
    requisition = _requisition_summary(
        ctx.request("GET", f"{HR}/requisitions/{payload['requisition_id']}")
    )
    if requisition["status"] != "open":
        raise CLIError("Only an open requisition can receive applications.", CONFLICT)
    candidate = _candidate_summary(ctx.request("GET", f"{HR}/candidates/{payload['candidate_id']}"))
    path = f"{HR}/applications"
    pair = {key: payload[key] for key in ("requisition_id", "candidate_id")}
    if ctx.request("GET", path, params={**pair, "limit": 1})["total"]:
        raise CLIError("The candidate already has an application for this requisition.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "requisition": requisition,
            "candidate_id": candidate["id"],
            "candidate_code": candidate["candidate_code"],
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "POST",
        path,
        json={**payload, "expected_requisition_updated_at": requisition["updated_at"]},
        write=True,
    )
    result = verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/{saved['id']}"),
        lambda observed: (
            observed["id"] == saved["id"]
            and observed["stage"] == "applied"
            and all(observed[key] == value for key, value in payload.items())
        ),
    )
    result.data = {**_application_summary(result.data), **pair}
    return result


def _decide_application_stage(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        request = ApplicationStageUpdateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply valid private application stage JSON.") from None
    if (
        request.stage in {"applied", "hired", "withdrawn"}
        or request.expected_updated_at is not None
    ):
        raise CLIError("Use application creation, onboarding or withdrawal for that action.")
    reason = (request.rejection_reason or "").strip()
    if (request.stage == "rejected") != bool(reason):
        raise CLIError("A rejection reason is required only when rejecting.")
    payload = request.model_dump(mode="json", exclude_none=True)
    path = f"{HR}/applications/{args.application_id}"
    current = _application_status(args, ctx)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "application": current,
            "stage": request.stage,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "PATCH",
        f"{path}/stage",
        json={**payload, "expected_updated_at": current["updated_at"]},
        write=True,
    )
    result = verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda observed: (
            observed["stage"] == request.stage
            and all(observed[key] == saved[key] for key in payload)
        ),
    )
    result.data = _application_summary(result.data)
    return result


def _withdraw_application(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        withdrawal = ApplicationWithdrawalRequest.model_validate_json(
            read_private_bytes(Path(args.decision_file), max_bytes=4096)
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Supply a private JSON file with a valid withdrawal decision.") from None
    current = _application_status(args, ctx)
    if current["stage"] != withdrawal["expected_stage"]:
        raise CLIError("Review the current application stage before withdrawing.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "application": current,
            "decision_sha256": sha256_json(withdrawal),
            "retention": {
                key: value for key, value in withdrawal.items() if key.startswith("retention_")
            },
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "PATCH",
        f"{HR}/applications/{args.application_id}/stage",
        json={
            "stage": "withdrawn",
            "withdrawal": withdrawal,
            "expected_updated_at": current["updated_at"],
        },
        write=True,
    )
    return verified(
        ctx,
        lambda: _application_status(args, ctx),
        lambda current: (
            current["stage"] == "withdrawn"
            and bool(current["withdrawn_at"])
            and current["withdrawn_at"] == saved["withdrawn_at"]
            and all(current[key] == value for key, value in plan["retention"].items())
        ),
    )


def _shortlist_application(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    application = _application_status(args, ctx)
    if application["stage"] != "screening":
        raise CLIError("Only an application in screening can be shortlisted.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "application": application, "stage": "shortlisted"},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "PATCH",
        f"{HR}/applications/{args.application_id}/stage",
        json={"stage": "shortlisted", "expected_updated_at": application["updated_at"]},
        write=True,
    )
    return verified(
        ctx, lambda: _application_status(args, ctx), lambda row: row["stage"] == "shortlisted"
    )


def _interview_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "id",
            "application_id",
            "round_number",
            "interview_type",
            "scheduled_at",
            "interviewer_user_id",
            "recommendation",
            "status",
            "updated_at",
        )
    }


def _interview_list(ctx: Context, application_id: str) -> dict[str, Any]:
    return ctx.request("GET", f"{HR}/interviews", params={"application_id": application_id})


def _list_interviews(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = _interview_list(ctx, args.application_id)
    return {
        "items": [_interview_summary(row) for row in listing["items"]],
        "total": listing["total"],
    }


def _interview_record(ctx: Context, application_id: str, interview_id: str) -> dict[str, Any]:
    for row in _interview_list(ctx, application_id)["items"]:
        if row["id"] == interview_id and row["application_id"] == application_id:
            return row
    raise CLIError("The interview is unavailable for this application.", CONFLICT)


def _schedule_interview(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        request = InterviewCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=8192), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private interview schedule JSON file.") from None
    if request.interview_id is None or request.expected_application_updated_at is not None:
        raise CLIError(
            "Specify a new interview UUID. The CLI supplies the application precondition."
        )
    if request.scheduled_at is None or request.scheduled_at.utcoffset() is None:
        raise CLIError("The schedule must include an interview time with its UTC offset.")
    args.application_id = str(request.application_id)
    application = _application_status(args, ctx)
    if application["stage"] not in {"shortlisted", "interview", "evaluation"}:
        raise CLIError("Shortlist the application before scheduling an interview.", CONFLICT)
    schedule = request.model_dump(mode="json", exclude={"expected_application_updated_at"})
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "application": application,
            "interview_id": str(request.interview_id),
            "scheduled_at": schedule["scheduled_at"],
            "schedule_sha256": sha256_json(schedule),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "POST",
        f"{HR}/interviews",
        json={**schedule, "expected_application_updated_at": application["updated_at"]},
        write=True,
    )
    return verified(
        ctx,
        lambda: _interview_summary(
            _interview_record(ctx, args.application_id, str(request.interview_id))
        ),
        lambda observed: (
            observed["id"] == str(request.interview_id) and observed == _interview_summary(saved)
        ),
    )


def _update_interview(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        request = InterviewUpdateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024), extra="forbid"
        )
    except ValidationError:
        raise CLIError("Supply a valid private interview update JSON file.") from None
    edits = request.model_dump(mode="json", exclude_none=True)
    if not edits or "expected_updated_at" in edits:
        raise CLIError("Specify interview changes. The CLI supplies the update precondition.")
    current = _interview_record(ctx, args.application_id, args.interview_id)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "interview": _interview_summary(current),
            "changes_sha256": sha256_json(edits),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "PATCH",
        f"{HR}/interviews/{args.interview_id}",
        json={**edits, "expected_updated_at": current["updated_at"]},
        write=True,
    )
    result = verified(
        ctx,
        lambda: _interview_record(ctx, args.application_id, args.interview_id),
        lambda observed: (
            _interview_summary(observed) == _interview_summary(saved)
            and all(observed[key] == saved[key] for key in edits)
        ),
    )
    result.data = _interview_summary(result.data)
    return result


def _correspondence_path(args: argparse.Namespace) -> str:
    return f"{HR}/applications/{args.application_id}/correspondence"


def _correspondence_templates(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    templates = ctx.request("GET", f"{HR}/candidate-correspondence/templates")
    return {
        "items": [
            {key: row[key] for key in ("id", "name", "is_active")} for row in templates["items"]
        ],
        "total": templates["total"],
    }


def _correspondence_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: record[key]
        for key in ("id", "status", "digest", "can_decide", "created_at", "decided_at")
    }


def _correspondence_status(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    record = ctx.request("GET", f"{_correspondence_path(args)}/{args.draft_id}")
    if args.output is not None:
        content = {key: record[key] for key in ("subject", "body", "rejection_reason", "digest")}
        try:
            write_private_bytes(
                args.output, (json.dumps(content, ensure_ascii=False) + "\n").encode()
            )
        except OSError:
            raise CLIError("Could not write a new private correspondence file.") from None
    return _correspondence_summary(record)


def _draft_correspondence(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    application = _application_status(args, ctx)
    if application["stage"] != "rejected":
        raise CLIError("Only a rejected application can have rejection correspondence.", CONFLICT)
    payload = {"draft_id": args.draft_id, "template_id": args.template_id}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "application": application, **payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    path = _correspondence_path(args)
    saved = ctx.request("POST", path, json=payload, write=True)
    return verified(
        ctx,
        lambda: _correspondence_summary(ctx.request("GET", f"{path}/{args.draft_id}")),
        lambda observed: (
            observed["id"] == args.draft_id
            and observed["status"] == saved["status"]
            and observed["digest"] == saved["digest"]
        ),
    )


def _decide_correspondence(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_RECRUITMENT)
    try:
        reason = (
            read_private_bytes(args.reason_file, max_bytes=8192).decode()
            if args.reason_file
            else None
        )
        payload = CandidateCorrespondenceDecisionRequest(
            decision=args.decision, expected_digest=args.content_sha256, reason=reason
        ).model_dump(mode="json")
    except (UnicodeDecodeError, ValidationError):
        raise CLIError(
            "Supply a valid content digest and a private UTF-8 reason file if rejecting."
        ) from None
    if (args.decision == "rejected") != bool(payload["reason"]) or (
        args.decision == "approved" and args.reason_file is not None
    ):
        raise CLIError("Supply a nonempty reason file only when rejecting.")
    path = f"{_correspondence_path(args)}/{args.draft_id}"
    current = _correspondence_summary(ctx.request("GET", path))
    if current["digest"] != args.content_sha256:
        raise CLIError("Review the exact correspondence before deciding.", CONFLICT)
    if not current["can_decide"] or current["status"] != "draft":
        raise CLIError("An eligible independent reviewer must decide a pending draft.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "application_id": args.application_id,
            "draft": current,
            "decision": args.decision,
            "decision_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/decision", json=payload, write=True)
    return verified(
        ctx,
        lambda: _correspondence_summary(ctx.request("GET", path)),
        lambda observed: (
            observed["id"] == args.draft_id
            and observed["digest"] == args.content_sha256
            and observed["status"] == args.decision
            and bool(observed["decided_at"])
        ),
    )


def _payroll_policy_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key] for key in (
            "id", "code", "is_approved", "approved_by_id", "second_approved_by_id", "updated_at"
        )
    }


def _list_payroll_policies(_args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    require_preview_permission(ctx, PERM_PAYROLL_PREPARE)
    rows = ctx.request("GET", f"{HR}/payroll/policies")
    return {
        "items": [_payroll_policy_summary(row) for row in rows["items"]],
        "total": rows["total"],
    }


def _read_payroll_policy(ctx: Context, policy_id: str) -> dict[str, Any]:
    row: dict[str, Any] = ctx.request("GET", f"{HR}/payroll/policies/{policy_id}")
    if row["id"] != policy_id:
        raise CLIError("The response does not match the requested payroll policy.", CONFLICT)
    return row


def _show_payroll_policy(args: argparse.Namespace, ctx: Context) -> Result:
    _require_any_permission(ctx, PERM_PAYROLL_PREPARE, PERM_PAYROLL_APPROVE)
    row = _read_payroll_policy(ctx, args.policy_id)
    try:
        write_private_bytes(args.output, (json.dumps(row, ensure_ascii=False) + "\n").encode())
    except OSError:
        raise CLIError("Could not write the private payroll policy file.") from None
    return Result({**_payroll_policy_summary(row), "review_sha256": sha256_json(row)})


def _save_payroll_policy(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_PREPARE)
    path = f"{HR}/payroll/policies"
    current = None
    if args.policy_id:
        current = _read_payroll_policy(ctx, args.policy_id)
        if current["approved_by_id"] != ctx.identity()["id"] or current["is_approved"]:
            raise CLIError("The preparer can only edit their own pending payroll policy.", CONFLICT)
    try:
        raw = json.loads(read_private_bytes(args.file, max_bytes=64 * 1024))
        if not isinstance(raw, dict) or "expected_updated_at" in raw:
            raise ValueError
        if current is None:
            policy = PayrollPolicyCreateRequest.model_validate(raw, extra="forbid")
            if policy.controlled_record is None:
                raise ValueError
            payload = policy.model_dump(mode="json")
            payload["code"] = payload["code"].strip()
        else:
            payload = PayrollPolicyDraftUpdateRequest.model_validate(
                {**raw, "expected_updated_at": current["updated_at"]}
            ).model_dump(mode="json")
        payload["name"] = payload["name"].strip()
    except ValueError:
        raise CLIError(
            "Supply a valid controlled payroll policy in an owner-only JSON file."
        ) from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "current": _payroll_policy_summary(current) if current else None,
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if current is None:
        saved = ctx.request("POST", path, json=payload, write=True)
    else:
        saved = ctx.request("PUT", f"{path}/{args.policy_id}/draft", json=payload, write=True)
    observed = verified(
        ctx,
        lambda: _read_payroll_policy(ctx, args.policy_id or saved["id"]),
        lambda row: (
            row == saved and not row["is_approved"]
            and all(
                row[key] == value for key, value in payload.items() if key != "expected_updated_at"
            )
        ),
    )
    return Result(_payroll_policy_summary(observed.data), changed=observed.changed)


def _approve_payroll_policy(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    row = _read_payroll_policy(ctx, args.policy_id)
    if row["is_approved"] or row["approved_by_id"] == ctx.identity()["id"]:
        raise CLIError("A different reviewer must approve a pending policy.", CONFLICT)
    digest = sha256_json(row)
    if digest != args.review_sha256:
        raise CLIError("The payroll policy changed. Save a new copy for review.", CONFLICT)
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "current": _payroll_policy_summary(row),
            "review_sha256": digest,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "POST", f"{HR}/payroll/policies/{args.policy_id}/approve",
        json={"expected_updated_at": row["updated_at"]}, write=True,
    )
    observed = verified(
        ctx,
        lambda: _read_payroll_policy(ctx, args.policy_id),
        lambda result: (
            result == saved and result["is_approved"]
            and result["second_approved_by_id"] == ctx.identity()["id"]
            and all(result[field] == row[field] for field in ("rules_json", "controlled_record"))
        ),
    )
    return Result(_payroll_policy_summary(observed.data), changed=observed.changed)


def _calculate_payroll(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_PREPARE)
    roster = load_json(Path(args.roster_file), max_bytes=64 * 1024)
    if not isinstance(roster, list) or not 1 <= len(roster) <= 1000:
        raise CLIError("Supply a JSON array of 1 to 1,000 employee IDs.")
    if any(not isinstance(value, str) for value in roster):
        raise CLIError("Enter employee IDs as UUID strings.")
    try:
        employee_ids = sorted(uuid_arg(value) for value in roster)
    except argparse.ArgumentTypeError as exc:
        raise CLIError("The payroll roster contains an invalid UUID.") from exc
    if len(set(employee_ids)) != len(employee_ids):
        raise CLIError("The payroll roster contains duplicate IDs.")
    path = f"{HR}/payroll/runs/{args.run_id}"
    run = ctx.request("GET", path)
    if run["prepared_by_id"] != ctx.identity()["id"] or run["status"] != "draft":
        raise CLIError("The preparer must calculate their own draft payroll run.", CONFLICT)
    evidence = None
    if args.time_sha256 is not None or args.leave_sha256 is not None:
        evidence = {"time_sha256": args.time_sha256, "leave_sha256": args.leave_sha256}
    try:
        payload = PayrollSnapshotCalculateRequest.model_validate(
            {"employee_ids": employee_ids, "source_evidence": evidence}
        ).model_dump(mode="json", exclude_none=True)
    except ValidationError:
        raise CLIError("Provide both the reviewed time and leave SHA-256 checksums.") from None
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "run": run, "roster": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{path}/calculate", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: (
            row["status"] == "calculated"
            and bool(row["snapshot_digest"])
            and row["snapshot_digest"] == saved["snapshot_digest"]
        ),
    )


def _approve_payroll(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    path = f"{HR}/payroll/runs/{args.run_id}"
    snapshot = ctx.request("GET", f"{path}/snapshot")
    if snapshot["status"] != "calculated":
        raise CLIError("Only a calculated snapshot can be approved.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "snapshot": snapshot},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "POST",
        f"{path}/approve",
        json={"expected_snapshot_digest": snapshot["digest"]},
        write=True,
    )
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/snapshot"),
        lambda row: row["status"] == "approved" and row["digest"] == snapshot["digest"],
    )


def _publish_payslips(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    path = f"{HR}/payroll/runs/{args.run_id}"
    snapshot = ctx.request("GET", f"{path}/snapshot")
    if snapshot["status"] != "approved":
        raise CLIError("Only an approved snapshot can be published.", CONFLICT)
    if snapshot["payslips_published_at"] is not None:
        return Result(
            {"run_id": args.run_id, "published_at": snapshot["payslips_published_at"]},
            outcome="unchanged",
        )
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "run_id": args.run_id,
            "digest": snapshot["digest"],
            "period_start": snapshot["period_start"],
            "period_end": snapshot["period_end"],
            "employee_count": len(snapshot["lines"]),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    receipt = ctx.request(
        "POST",
        f"{path}/publish-payslips",
        json={"expected_snapshot_digest": snapshot["digest"]},
        write=True,
    )
    return verified(
        ctx,
        lambda: {
            key: value
            for key, value in ctx.request("GET", f"{path}/snapshot").items()
            if key in {"run_id", "digest", "payslips_published_at"}
        },
        lambda row: (
            row["digest"] == receipt["snapshot_digest"]
            and row["payslips_published_at"] == receipt["published_at"]
        ),
    )


def _register_payroll_export(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    path = f"{HR}/payroll/runs/{args.run_id}/payment-export"
    preview = ctx.request("GET", f"{path}/preview")
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "approved_handoff": preview},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    existing = preview.get("receipt")
    if existing:
        return Result(existing, outcome="unchanged")
    saved = ctx.request(
        "POST",
        path,
        write=True,
        json={
            "expected_snapshot_digest": preview["snapshot_digest"],
            "expected_csv_sha256": preview["csv_sha256"],
        },
    )
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/preview")["receipt"],
        lambda receipt: receipt == saved and receipt["csv_sha256"] == preview["csv_sha256"],
    )


def _download_payroll_export(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    expected = args.sha256
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise CLIError("Provide the registered CSV SHA-256.")
    with ctx.stream("GET", f"{HR}/payroll/runs/{args.run_id}/payment-export") as response:
        if (
            response.headers.get("content-type", "").split(";", 1)[0] != "text/csv"
            or response.headers.get("x-payroll-export-sha256") != expected
        ):
            raise CLIError("The download headers do not match the registered export.", CONFLICT)
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            content.extend(chunk)
            if len(content) > 256 * 1024:
                raise CLIError("The payment export exceeds the expected size limit.")
    if hashlib.sha256(content).hexdigest() != expected:
        raise CLIError("The downloaded file does not match the registered export.", CONFLICT)
    try:
        write_private_bytes(Path(args.output), bytes(content))
    except OSError:
        raise CLIError("Could not create a new private payout file.") from None
    return Result({"run_id": args.run_id, "csv_sha256": expected, "size_bytes": len(content)})


def _payroll_inputs(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_PREPARE)
    try:
        roster = PayrollRunCalculateRequest.model_validate(
            {
                "employee_ids": json.loads(
                    read_private_bytes(Path(args.roster_file), max_bytes=64 * 1024)
                )
            }
        )
    except ValueError:
        raise CLIError("Provide a private JSON array of unique employee UUIDs.") from None
    source = args.input_source
    path = f"{HR}/payroll/periods/{args.period_id}/{source}-inputs"
    payload = roster.model_dump(mode="json")
    if args.output is None:
        return Result(ctx.request("POST", f"{path}/preview", json=payload))
    if not args.sha256 or re.fullmatch(r"[0-9a-f]{64}", args.sha256) is None:
        raise CLIError(f"Provide --sha256 from the current {source} input preview.")
    payload["expected_csv_sha256"] = args.sha256
    with ctx.stream("POST", f"{path}.csv", json=payload) as response:
        if (
            response.headers.get("content-type", "").split(";", 1)[0] != "text/csv"
            or response.headers.get("x-payroll-export-sha256") != args.sha256
        ):
            raise CLIError(
                f"The download headers do not match the {source} input preview.", CONFLICT
            )
        content = bytearray()
        for chunk in response.iter_bytes(chunk_size=65536):
            content.extend(chunk)
            if len(content) > 8 * 1024 * 1024:
                raise CLIError(f"The {source} input export exceeds the expected size limit.")
    if hashlib.sha256(content).hexdigest() != args.sha256:
        raise CLIError(f"The downloaded file does not match the {source} input preview.", CONFLICT)
    try:
        write_private_bytes(Path(args.output), bytes(content))
    except OSError:
        raise CLIError(f"Could not create a new private {source} input file.") from None
    return Result(
        {"period_id": args.period_id, "csv_sha256": args.sha256, "size_bytes": len(content)}
    )


def _benefit_type_metadata(row: BenefitTypeResponse) -> dict[str, Any]:
    summary = row.model_dump(mode="json", exclude={"reimbursement_ceiling"})
    return {**summary, "has_ceiling": row.reimbursement_ceiling is not None}


def _benefit_types(ctx: Context) -> BenefitTypeListResponse:
    try:
        return BenefitTypeListResponse.model_validate(ctx.request("GET", f"{HR}/benefits/types"))
    except ValidationError:
        raise CLIError("The API returned an invalid benefit catalogue.", CONFLICT) from None


def _benefit_type(ctx: Context, benefit_type_id: str) -> BenefitTypeResponse:
    row = next((row for row in _benefit_types(ctx).items if str(row.id) == benefit_type_id), None)
    if row is None:
        raise CLIError("The benefit type was not found.", CONFLICT)
    return row


def _list_benefit_types(_: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    page_data = _benefit_types(ctx)
    return Result({
        "items": [_benefit_type_metadata(row) for row in page_data.items],
        "total": page_data.total,
    })


def _show_benefit_type(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    row = _benefit_type(ctx, args.benefit_type_id)
    if args.output is not None:
        try:
            write_private_bytes(args.output, (row.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not create a new private benefit review file.") from None
    return Result(_benefit_type_metadata(row))


def _propose_benefit_type(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        raw = json.loads(read_private_bytes(args.file, max_bytes=16 * 1024))
        if not isinstance(raw, dict):
            raise ValueError
        ceiling = raw.get("reimbursement_ceiling")
        if ceiling is not None and not isinstance(ceiling, str):
            raise ValueError
        if isinstance(raw.get("code"), str):
            raw["code"] = raw["code"].strip().upper()
        model = BenefitTypeCreateRequest.model_validate(raw, extra="forbid")
        capped = model.reimbursement_ceiling is not None
        if (
            capped != (model.reimbursement_currency is not None)
            or (capped and not model.requires_policy_approval)
            or (model.allows_advances and not capped)
        ):
            raise ValueError
    except ValueError:
        raise CLIError(
            "Supply owner-only benefit JSON with any reimbursement ceiling as decimal text."
        ) from None
    if any(row.code == model.code for row in _benefit_types(ctx).items):
        raise CLIError("This benefit code already exists.", CONFLICT)
    payload = model.model_dump(mode="json")
    plan = checked_plan(
        args, ctx,
        {"operation": args.command_name, "code": model.code,
         "request_sha256": sha256_json(payload)},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    row = ctx.request("POST", f"{HR}/benefits/types", json=payload, write=True)
    try:
        saved_id = uuid_arg(row["id"])
    except (argparse.ArgumentTypeError, KeyError, TypeError, AttributeError):
        raise CLIError("The API did not identify the saved benefit type.", CONFLICT) from None
    observed = verified(
        ctx,
        lambda: _benefit_type(ctx, saved_id),
        lambda saved: (
            all(getattr(saved, field) == value for field, value in model.model_dump().items())
            and saved.approved_at is None and saved.approved_by_id is None
            and (not capped or str(saved.proposed_by_id) == ctx.identity()["id"])
        ),
    )
    return Result(_benefit_type_metadata(observed.data), changed=observed.changed)


def _approve_benefit_type(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    try:
        reviewed = BenefitTypeResponse.model_validate(
            json.loads(read_private_bytes(args.review_file, max_bytes=16 * 1024)), extra="forbid"
        )
    except ValueError:
        raise CLIError("Supply an exact private benefit review file.") from None
    actor_id = ctx.identity()["id"]
    current = _benefit_type(ctx, str(reviewed.id))
    if current != reviewed or not current.is_active or current.approved_at is not None:
        raise CLIError("The benefit changed or is no longer pending. Review it again.", CONFLICT)
    if (
        current.reimbursement_ceiling is None
        or current.reimbursement_currency is None
        or current.proposed_by_id is None
        or str(current.proposed_by_id) == actor_id
    ):
        raise CLIError("A different eligible reviewer must approve a configured ceiling.", CONFLICT)
    plan = checked_plan(
        args, ctx,
        {"operation": args.command_name, "benefit_type": _benefit_type_metadata(current),
         "review_sha256": sha256_json(current.model_dump(mode="json"))},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/benefits/types/{current.id}/approve", write=True)
    observed = verified(
        ctx,
        lambda: _benefit_type(ctx, str(current.id)),
        lambda row: (
            str(row.approved_by_id) == actor_id and row.approved_at is not None
            and row.model_dump(exclude={"approved_by_id", "approved_at"})
            == reviewed.model_dump(exclude={"approved_by_id", "approved_at"})
        ),
    )
    return Result(_benefit_type_metadata(observed.data), changed=observed.changed)


def _benefit_assignments(ctx: Context, employee_id: str) -> EmployeeBenefitListResponse:
    try:
        result = EmployeeBenefitListResponse.model_validate(ctx.request(
            "GET", f"{HR}/benefits/assignments", params={"employee_id": employee_id}
        ))
        if any(str(item.employee_id) != employee_id for item in result.items):
            raise ValueError
        return result
    except ValueError:
        raise CLIError("The API returned invalid employee benefit assignments.", CONFLICT) from None


def _benefit_assignment_metadata(row: EmployeeBenefitResponse) -> dict[str, Any]:
    return row.model_dump(mode="json", exclude={"coverage_notes"})


def _list_benefit_assignments(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    page_data = _benefit_assignments(ctx, args.employee_id)
    return Result({
        "items": [_benefit_assignment_metadata(row) for row in page_data.items],
        "total": page_data.total,
    })


def _assign_benefit(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        model = EmployeeBenefitCreateRequest.model_validate(
            json.loads(read_private_bytes(args.file, max_bytes=16 * 1024)), extra="forbid"
        )
        if model.effective_to is not None and model.effective_to < model.effective_from:
            raise ValueError
    except ValueError:
        raise CLIError("Supply valid dates in an owner-only coverage JSON file.") from None
    benefit = _benefit_type(ctx, str(model.benefit_type_id))
    if not benefit.is_active:
        raise CLIError("This benefit type is inactive.", CONFLICT)
    if benefit.reimbursement_ceiling is not None:
        if (
            benefit.approved_at is None
            or benefit.reimbursement_currency is None
            or benefit.proposed_by_id is None
            or benefit.approved_by_id is None
            or benefit.proposed_by_id == benefit.approved_by_id
        ):
            raise CLIError("The capped benefit needs an independently approved policy.", CONFLICT)
        if model.effective_to is None:
            raise CLIError("A capped benefit needs a coverage end date.")
    employee_id = str(model.employee_id)
    current = _benefit_assignments(ctx, employee_id)
    same_benefit = [row for row in current.items if row.benefit_type_id == model.benefit_type_id]
    if any(
        row.status == "active"
        and (row.effective_to is None or row.effective_to >= model.effective_from)
        and (model.effective_to is None or row.effective_from <= model.effective_to)
        for row in same_benefit
    ):
        raise CLIError("This benefit overlaps existing coverage.", CONFLICT)
    payload = model.model_dump(mode="json")
    plan = checked_plan(
        args, ctx,
        {"operation": args.command_name, "employee_id": employee_id,
         "benefit_type": _benefit_type_metadata(benefit),
         "benefit_sha256": sha256_json(benefit.model_dump(mode="json")),
         "observed_assignments": [_benefit_assignment_metadata(row) for row in same_benefit],
         "request_sha256": sha256_json(payload)},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{HR}/benefits/assignments", json=payload, write=True)
    try:
        assignment_id = uuid_arg(saved["id"])
    except (argparse.ArgumentTypeError, KeyError, TypeError, AttributeError):
        raise CLIError("The API did not identify the saved assignment.", CONFLICT) from None

    def readback() -> EmployeeBenefitResponse:
        row = next((
            row for row in _benefit_assignments(ctx, employee_id).items
            if str(row.id) == assignment_id
        ), None)
        if row is None:
            raise CLIError("The saved assignment was not found.", CONFLICT)
        return row

    observed = verified(
        ctx, readback,
        lambda row: row.status == "active" and all(
            getattr(row, field) == value for field, value in model.model_dump().items()
        ),
    )
    return Result(_benefit_assignment_metadata(observed.data), changed=observed.changed)


def _compensation_summary(row: CompensationTermResponse) -> dict[str, Any]:
    return row.model_dump(
        mode="json",
        exclude={"base_salary_plain", "base_salary_masked", "allowances_json", "rejection_reason"},
    )


def _compensation_rows(
    ctx: Context, employee_id: str, *, term_id: str | None = None, reveal: bool = False
) -> CompensationTermListResponse:
    try:
        rows = CompensationTermListResponse.model_validate(ctx.request(
            "GET",
            f"{HR}/compensation/{employee_id}",
            params={
                **({"term_id": term_id} if term_id else {}),
                **({"reveal_sensitive": "true"} if reveal else {}),
            },
        ))
        if any(
            str(row.employee_id) != employee_id or (term_id and str(row.id) != term_id)
            for row in rows.items
        ):
            raise ValueError
        return rows
    except ValueError:
        raise CLIError("The API returned an invalid compensation record.", CONFLICT) from None


def _compensation_exact(
    ctx: Context, employee_id: str, term_id: str, *, reveal: bool = False
) -> CompensationTermResponse:
    result = _compensation_rows(ctx, employee_id, term_id=term_id, reveal=reveal)
    if len(result.items) != 1 or (reveal and result.items[0].base_salary_plain is None):
        raise CLIError("The API did not return the exact compensation term.", CONFLICT)
    return result.items[0]


def _list_compensation(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    rows = _compensation_rows(ctx, args.employee_id)
    items = [_compensation_summary(row) for row in rows.items]
    return Result({"items": items, "total": rows.total})


def _show_compensation(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    row = _compensation_exact(ctx, args.employee_id, args.term_id, reveal=args.output is not None)
    if args.output is not None:
        try:
            write_private_bytes(args.output, (row.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not create a new private compensation file.") from None
    return Result(_compensation_summary(row))


def _propose_compensation(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        model = CompensationTermCreateRequest.model_validate(
            json.loads(read_private_bytes(args.file, max_bytes=16 * 1024)), extra="forbid"
        )
    except ValueError:
        raise CLIError("Supply valid compensation terms in an owner-only JSON file.") from None
    payload = model.model_dump(mode="json")
    payload["allowances_json"] = model.allowances_json or None
    employee_id = str(model.employee_id)
    current = _compensation_rows(ctx, employee_id)
    if any(
        row.approval_status == "proposed"
        or (row.approval_status == "approved" and row.effective_from == model.effective_from)
        for row in current.items
    ):
        raise CLIError("A conflicting compensation term already exists.", CONFLICT)
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "employee_id": employee_id,
            "effective_from": payload["effective_from"],
            "observed_terms": [_compensation_summary(row) for row in current.items],
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{HR}/compensation", json=payload, write=True)
    try:
        term_id = uuid_arg(saved["id"])
    except (argparse.ArgumentTypeError, KeyError, TypeError, AttributeError):
        raise CLIError("The API did not identify the proposed term.", CONFLICT) from None
    observed = verified(
        ctx,
        lambda: _compensation_exact(ctx, employee_id, term_id, reveal=True),
        lambda row: (
            row.approval_status == "proposed"
            and str(row.proposed_by_id) == ctx.identity()["id"]
            and row.effective_from == model.effective_from
            and row.currency == model.currency
            and row.pay_frequency == model.pay_frequency
            and row.base_salary_plain == model.base_salary
            and row.allowances_json == payload["allowances_json"]
        ),
    )
    return Result(_compensation_summary(observed.data), changed=observed.changed)


def _decide_compensation(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    try:
        reviewed = CompensationTermResponse.model_validate(
            json.loads(read_private_bytes(args.review_file, max_bytes=32 * 1024)), extra="forbid"
        )
        decision = CompensationTermDecisionRequest.model_validate(
            json.loads(read_private_bytes(args.file, max_bytes=4096)), extra="forbid"
        )
        if decision.decision == "reject" and not (decision.reason or "").strip():
            raise ValueError
    except ValueError:
        raise CLIError("Supply an exact private review file and valid decision JSON.") from None
    current = _compensation_exact(ctx, str(reviewed.employee_id), str(reviewed.id), reveal=True)
    if current != reviewed or current.approval_status != "proposed":
        raise CLIError("The compensation term changed. Review a fresh copy.", CONFLICT)
    actor_id = ctx.identity()["id"]
    if current.proposed_by_id is None or str(current.proposed_by_id) == actor_id:
        raise CLIError("Another authorized reviewer must decide the proposal.", CONFLICT)
    payload = decision.model_dump(mode="json")
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "term": _compensation_summary(current),
            "review_sha256": sha256_json(current.model_dump(mode="json")),
            "decision": decision.decision,
            "decision_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/compensation/{reviewed.id}/decision", json=payload, write=True)
    observed = verified(
        ctx,
        lambda: _compensation_exact(ctx, str(reviewed.employee_id), str(reviewed.id), reveal=True),
        lambda row: (
            row.approval_status == ("approved" if decision.decision == "approve" else "rejected")
            and row.effective_from == reviewed.effective_from
            and row.currency == reviewed.currency
            and row.pay_frequency == reviewed.pay_frequency
            and row.base_salary_plain == reviewed.base_salary_plain
            and row.allowances_json == reviewed.allowances_json
            and (
                str(row.approved_by_id) == actor_id if decision.decision == "approve"
                else row.rejection_reason == (decision.reason or "").strip()
            )
        ),
    )
    return Result(_compensation_summary(observed.data), changed=observed.changed)


def _advance_metadata(row: EmployeeAdvanceResponse) -> dict[str, Any]:
    return {
        "advance_id": str(row.id),
        "employee_id": str(row.employee_id),
        "status": row.status,
        "payable_sha256": row.payable_sha256,
        "repayment_count": len(row.recoveries),
    }


def _advance_details(ctx: Context, advance_id: str) -> EmployeeAdvanceResponse:
    try:
        row = EmployeeAdvanceResponse.model_validate(
            ctx.request("GET", f"{HR}/advances/{advance_id}")
        )
    except ValidationError:
        raise CLIError("The API returned an invalid advance record.", CONFLICT) from None
    if str(row.id) != advance_id:
        raise CLIError("The API returned a different advance.", CONFLICT)
    return row


def _list_advances(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        result = EmployeeAdvanceListResponse.model_validate(
            ctx.request(
                "GET", f"{HR}/advances", params=query(args, "employee_id", "limit", "offset")
            )
        )
    except ValidationError:
        raise CLIError("The API returned an invalid list of advances.", CONFLICT) from None
    if any(str(row.employee_id) != args.employee_id for row in result.items):
        raise CLIError("The API returned advances for a different employee.", CONFLICT)
    return Result(
        {"items": [_advance_metadata(row) for row in result.items], "total": result.total}
    )


def _show_advance(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    row = _advance_details(ctx, args.advance_id)
    if args.output:
        try:
            write_private_bytes(args.output, (row.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not create a new private advance file.") from None
    return Result(_advance_metadata(row))


def _advance_input(path: Path, required: set[str]) -> dict[str, Any]:
    try:
        values = json.loads(read_private_bytes(path, max_bytes=16 * 1024))
        if not isinstance(values, dict) or values.keys() != required:
            raise ValueError
        if not isinstance(values.get("amount"), str):
            raise ValueError
    except ValueError:
        raise CLIError(
            "Supply the required fields in a private JSON file with amount as text."
        ) from None
    return values


def _submit_advance(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    values = _advance_input(
        args.file, set(EmployeeAdvanceRequest.model_fields) | {"idempotency_key"}
    )
    try:
        key = uuid_arg(values.pop("idempotency_key"))
        payload = EmployeeAdvanceRequest.model_validate(values)
    except (ValidationError, argparse.ArgumentTypeError, AttributeError, TypeError):
        raise CLIError("The advance request fields are invalid.") from None
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "employee_id": str(payload.employee_id),
            "benefit_assignment_id": str(payload.benefit_assignment_id),
            "request_sha256": sha256_json([key, payload.model_dump(mode="json")]),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "POST",
        f"{HR}/advances",
        json=payload.model_dump(mode="json"),
        headers={"Idempotency-Key": key},
        write=True,
    )

    def readback() -> dict[str, Any]:
        try:
            saved_id = uuid_arg(saved["id"])
        except (argparse.ArgumentTypeError, KeyError, AttributeError, TypeError):
            raise CLIError("The API did not identify the new advance.", CONFLICT) from None
        row = _advance_details(ctx, saved_id)
        if any(getattr(row, field) != value for field, value in payload.model_dump().items()):
            raise CLIError("The recorded advance does not match the submission.", CONFLICT)
        return _advance_metadata(row)

    return verified(ctx, readback, bool)


def _change_advance(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    current = _advance_details(ctx, args.advance_id)
    action = args.advance_action
    payload: EmployeeAdvanceDecision | EmployeeAdvancePayment
    if action == "decision":
        if current.status != "submitted":
            raise CLIError("Only submitted advances can be decided.", CONFLICT)
        payload = EmployeeAdvanceDecision(decision=args.decision)
    else:
        input_model = (
            EmployeeAdvanceDisbursement if action == "disburse" else EmployeeAdvancePayment
        )
        normalized = _advance_input(args.file, set(input_model.model_fields))
        try:
            normalized["reference"] = (
                str(normalized["reference"]).strip()
                if isinstance(normalized["reference"], str)
                else normalized["reference"]
            )
            payload = input_model.model_validate(normalized)
        except ValidationError:
            raise CLIError("The external payment fields are invalid.") from None
        if payload.currency != current.currency:
            raise CLIError("The external payment currency differs from the advance.", CONFLICT)
        if isinstance(payload, EmployeeAdvanceDisbursement):
            if (
                current.status != "approved"
                or payload.expected_payable_sha256 != current.payable_sha256
                or payload.amount != current.amount
            ):
                raise CLIError(
                    "The external disbursement must match the approved advance.", CONFLICT
                )
        elif (
            current.status != "disbursed"
            or payload.amount > current.outstanding
            or payload.reference == current.disbursement_reference
            or any(item.reference == payload.reference for item in current.recoveries)
        ):
            raise CLIError(
                "The repayment must be new and within the outstanding principal.", CONFLICT
            )
    body = payload.model_dump(mode="json")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "advance_id": args.advance_id,
            "current_status": current.status,
            "state_sha256": sha256_json(current.model_dump(mode="json")),
            "request_sha256": sha256_json(body),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/advances/{args.advance_id}/{action}", json=body, write=True)

    def readback() -> dict[str, Any]:
        row = _advance_details(ctx, args.advance_id)
        if isinstance(payload, EmployeeAdvanceDecision):
            matches = row.status == payload.decision
        elif isinstance(payload, EmployeeAdvanceDisbursement):
            matches = (
                row.status in {"disbursed", "settled"}
                and row.disbursement_reference == payload.reference
                and row.disbursed_on == payload.occurred_on
                and row.payable_sha256 == payload.expected_payable_sha256
            )
        else:
            matches = any(
                (item.reference, item.occurred_on, item.amount)
                == (payload.reference, payload.occurred_on, payload.amount)
                for item in row.recoveries
            )
        if not matches:
            raise CLIError("The advance record does not match the reviewed operation.", CONFLICT)
        return _advance_metadata(row)

    return verified(ctx, readback, lambda row: row["advance_id"] == args.advance_id)


def _read_reimbursement_payable(ctx: Context, claim_id: str) -> ReimbursementPayableResponse:
    try:
        result = ReimbursementPayableResponse.model_validate(
            ctx.request("GET", f"{HR}/reimbursements/{claim_id}/payable")
        )
    except ValidationError:
        raise CLIError("The portal returned an invalid payable reference.", CONFLICT) from None
    reference = result.reference.model_dump(mode="json")
    if (
        str(result.reference.claim_id) != claim_id
        or sha256_json(reference) != result.reference_sha256
    ):
        raise CLIError("The payable reference failed integrity verification.", CONFLICT)
    return result


def _reimbursement_metadata(row: ReimbursementOperatorResponse) -> dict[str, Any]:
    return row.model_dump(
        mode="json", exclude={"amount", "description", "settlement_reference", "decision_notes"}
    )


def _reimbursement_claim(ctx: Context, claim_id: str) -> ReimbursementOperatorResponse:
    try:
        row = ReimbursementOperatorResponse.model_validate(
            ctx.request("GET", f"{HR}/reimbursements/{claim_id}")
        )
    except ValidationError:
        raise CLIError("The API returned an invalid reimbursement.", CONFLICT) from None
    if str(row.id) != claim_id:
        raise CLIError("The API did not return the requested reimbursement.", CONFLICT)
    return row


def _list_reimbursements(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        page_data = ReimbursementOperatorListResponse.model_validate(
            ctx.request(
                "GET", f"{HR}/reimbursements",
                params=query(args, "employee_id", "limit", "offset"),
            )
        )
        if args.employee_id and any(
            str(item.employee_id) != args.employee_id for item in page_data.items
        ):
            raise ValueError
    except ValueError:
        raise CLIError("The API returned an invalid reimbursement list.", CONFLICT) from None
    return Result({
        "items": [_reimbursement_metadata(row) for row in page_data.items],
        "total": page_data.total,
    })


def _show_reimbursement(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    row = _reimbursement_claim(ctx, args.claim_id)
    if args.output is not None:
        try:
            write_private_bytes(args.output, (row.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not create a new private reimbursement file.") from None
    return Result(_reimbursement_metadata(row))


def _submit_reimbursement(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        data = json.loads(read_private_bytes(args.file, max_bytes=16 * 1024))
        if not isinstance(data, dict) or not isinstance(data.get("amount"), str):
            raise ValueError
        key = uuid_arg(data.pop("idempotency_key"))
        model = ReimbursementCreateRequest.model_validate(data, extra="forbid")
        if model.employee_id is None or len(model.claim_type.strip()) < 2:
            raise ValueError
    except (ValueError, KeyError, AttributeError, TypeError, argparse.ArgumentTypeError):
        raise CLIError(
            "Supply owner-only claim JSON with an employee ID, decimal-text amount, and retry key."
        ) from None
    payload = model.model_dump(mode="json")
    payload["claim_type"] = model.claim_type.strip().upper()
    plan = checked_plan(
        args, ctx,
        {"operation": args.command_name, "employee_id": payload["employee_id"],
         "benefit_assignment_id": payload["benefit_assignment_id"],
         "receipt_document_id": payload["receipt_document_id"],
         "receipt_version_number": payload["receipt_version_number"],
         "request_sha256": sha256_json([key, payload])},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    try:
        saved = ReimbursementOperatorResponse.model_validate(
            ctx.request(
                "POST", f"{HR}/reimbursements", json=payload,
                headers={"Idempotency-Key": key}, write=True,
            )
        )
    except ValidationError:
        raise CLIError("The API did not identify the saved claim.", changed=None) from None
    matches = model.model_dump(exclude={"receipt_version_number"})
    matches["claim_type"] = payload["claim_type"]
    observed = verified(
        ctx,
        lambda: _reimbursement_claim(ctx, str(saved.id)),
        lambda row: (
            row.receipt_version_id is not None
            and row.receipt_version_id == saved.receipt_version_id
            and str(row.submitted_by_id) == ctx.identity()["id"]
            and all(getattr(row, field) == value for field, value in matches.items())
        ),
    )
    return Result(_reimbursement_metadata(observed.data), changed=observed.changed)


def _decide_reimbursement(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    try:
        reviewed = ReimbursementOperatorResponse.model_validate(
            json.loads(read_private_bytes(args.review_file, max_bytes=16 * 1024)), extra="forbid"
        )
        data = json.loads(read_private_bytes(args.file, max_bytes=4096))
        if not isinstance(data, dict) or not data.keys() <= {"decision", "notes"}:
            raise ValueError
        decision = ReimbursementDecisionRequest.model_validate(data, extra="forbid")
        if decision.decision == "paid" or (
            decision.decision in {"rejected", "cancelled"} and not (decision.notes or "").strip()
        ):
            raise ValueError
    except ValueError:
        raise CLIError("Supply the private reviewed claim and a valid review decision.") from None
    actor_id = ctx.identity()["id"]
    current = _reimbursement_claim(ctx, str(reviewed.id))
    if (
        current != reviewed or current.status != "submitted" or current.receipt_version_id is None
        or current.submitted_by_id is None or str(current.submitted_by_id) == actor_id
    ):
        raise CLIError("An independent reviewer needs the current submitted claim.", CONFLICT)
    payload = decision.model_dump(mode="json", exclude_unset=True)
    plan = checked_plan(
        args, ctx,
        {"operation": args.command_name, "claim": _reimbursement_metadata(current),
         "review_sha256": sha256_json(current.model_dump(mode="json")),
         "decision": decision.decision, "decision_sha256": sha256_json(payload)},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/reimbursements/{current.id}/decision", json=payload, write=True)
    decision_fields = {"decided_by_id", "decided_at", "decision_notes", "status"}
    observed = verified(
        ctx,
        lambda: _reimbursement_claim(ctx, str(current.id)),
        lambda row: (
            row.status == decision.decision and str(row.decided_by_id) == actor_id
            and row.decided_at is not None and row.decision_notes == decision.notes
            and row.model_dump(exclude=decision_fields)
            == reviewed.model_dump(exclude=decision_fields)
        ),
    )
    return Result(_reimbursement_metadata(observed.data), changed=observed.changed)


def _reimbursement_payable(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    result = _read_reimbursement_payable(ctx, args.claim_id)
    if args.output:
        if result.status != "approved":
            raise CLIError("This payable is already settled.", CONFLICT)
        try:
            write_private_bytes(args.output, (result.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not create a new private payable file.") from None
    return Result(
        {
            "claim_id": args.claim_id,
            "payable_reference": result.reference.payable_reference,
            "reference_sha256": result.reference_sha256,
            "status": result.status,
        }
    )


def _confirm_reimbursement_paid(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    payable = _read_reimbursement_payable(ctx, args.claim_id)
    if payable.status != "approved":
        raise CLIError("This payable is already settled.", CONFLICT)
    try:
        file_values = json.loads(read_private_bytes(args.settlement_file, max_bytes=16 * 1024))
        if not isinstance(file_values, dict) or file_values.keys() != {
            "expected_payable_sha256",
            "settlement_reference",
            "settled_amount",
            "settled_currency",
        }:
            raise ValueError
        decision = ReimbursementDecisionRequest.model_validate(
            {
                "decision": "paid",
                **file_values,
            }
        )
    except ValueError:
        raise CLIError(
            "Provide the reviewed payable digest, external reference, amount and currency "
            "in a private JSON file."
        ) from None
    if (
        not (decision.settlement_reference or "").strip()
        or decision.expected_payable_sha256 != payable.reference_sha256
        or decision.settled_amount != payable.reference.amount
        or decision.settled_currency != payable.reference.currency
    ):
        raise CLIError("The external settlement must match the approved payable.", CONFLICT)
    payload = decision.model_dump(mode="json", exclude_none=True)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "claim_id": args.claim_id,
            "payable_sha256": payable.reference_sha256,
            "settlement_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/reimbursements/{args.claim_id}/decision", json=payload, write=True)

    def readback() -> dict[str, str]:
        current = _read_reimbursement_payable(ctx, args.claim_id)
        return {"status": current.status, "reference_sha256": current.reference_sha256}

    return verified(
        ctx,
        readback,
        lambda row: row["status"] == "paid" and row["reference_sha256"] == payable.reference_sha256,
    )


def _record_payroll_settlement(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    raw = read_private_bytes(Path(args.event_file))
    try:
        event = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise CLIError("Supply a valid private settlement event JSON file.") from exc
    required = {
        "event_id",
        "payment_reference",
        "kind",
        "amount",
        "occurred_on",
        "evidence_reference",
    }
    if (
        not isinstance(event, dict)
        or not required <= event.keys()
        or event.keys() - (required | {"reverses_event_id"})
    ):
        raise CLIError("The settlement file is missing fields or contains unsupported fields.")
    try:
        event_id = uuid_arg(event["event_id"])
        payment_reference = uuid_arg(event["payment_reference"])
    except (argparse.ArgumentTypeError, AttributeError, TypeError) as exc:
        raise CLIError("Supply valid settlement and payment UUIDs.") from exc
    path = f"{HR}/payroll/runs/{args.run_id}/settlements"
    summary = ctx.request("GET", path)
    payment = next(
        (row for row in summary["payments"] if row["payment_reference"] == payment_reference), None
    )
    if payment is None:
        raise CLIError("The payment reference is absent from the registered export.", CONFLICT)
    try:
        payload = PayrollSettlementRequest.model_validate(
            {
                **event,
                "event_id": event_id,
                "payment_reference": payment_reference,
                "expected_csv_sha256": summary["csv_sha256"],
            }
        ).model_dump(mode="json")
    except ValidationError as exc:
        raise CLIError("The settlement event fields failed validation.") from exc
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "run_id": args.run_id,
            "payment": payment,
            "csv_sha256": summary["csv_sha256"],
            "proposed_event": {
                key: value for key, value in payload.items() if key != "evidence_reference"
            },
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{path}/events", json=payload, write=True)
    return verified(
        ctx,
        lambda: {
            key: value
            for key, value in ctx.request("GET", f"{path}/events/{event_id}").items()
            if key != "evidence_reference"
        },
        lambda row: (
            bool(row)
            and row["id"] == saved["id"] == event_id
            and row["recorded_at"] == saved["recorded_at"]
        ),
    )


def _close_payroll(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    path = f"{HR}/payroll/runs/{args.run_id}"
    snapshot = ctx.request("GET", f"{path}/snapshot")
    summary = ctx.request("GET", f"{path}/settlements")
    if (
        snapshot["run_id"] != args.run_id
        or summary["run_id"] != args.run_id
        or snapshot["status"] != "approved"
        or not snapshot["payslips_published_at"]
        or not summary["fully_reconciled"]
    ):
        raise CLIError("Closure requires published payslips and full reconciliation.", CONFLICT)
    payload = {
        "expected_snapshot_digest": snapshot["digest"],
        "expected_csv_sha256": summary["csv_sha256"],
        "expected_settlement_digest": summary["settlement_digest"],
    }
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "run_id": args.run_id, **payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{path}/close", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/settlements")["closure"],
        lambda row: bool(row) and row == saved and row["run_id"] == args.run_id,
    )


def _payroll_corrections_path(args: argparse.Namespace) -> str:
    return f"{HR}/payroll/runs/{args.run_id}/lines/{args.line_id}/corrections"


def _correction_receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in ("id", "line_id", "previous_id", "snapshot_digest", "digest", "status")
    }


def _propose_payroll_correction(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_PREPARE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    try:
        detail = json.loads(read_private_bytes(Path(args.file), max_bytes=16 * 1024))
        if not isinstance(detail, dict) or detail.keys() != {
            "correction_id", "gross", "deductions", "evidence_reference"
        }:
            raise ValueError
    except (ValueError, UnicodeError):
        raise CLIError("Use a private JSON file with the four correction fields.") from None
    path = _payroll_corrections_path(args)
    snapshot = ctx.request("GET", f"{HR}/payroll/runs/{args.run_id}/snapshot")
    history = ctx.request("GET", path, params={"limit": 1})
    if snapshot["run_id"] != args.run_id or not snapshot["closed_at"]:
        raise CLIError("A correction requires the exact closed payroll snapshot.", CONFLICT)
    if history["line_id"] != args.line_id:
        raise CLIError("The correction baseline belongs to a different payroll line.", CONFLICT)
    try:
        payload = PayrollCorrectionCreate.model_validate({
            **detail,
            "expected_snapshot_digest": snapshot["digest"],
            "expected_previous_id": history["current_correction_id"],
        }).model_dump(mode="json")
    except ValidationError:
        raise CLIError("The private correction proposal fields failed validation.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "run_id": args.run_id,
            "line_id": args.line_id,
            "correction_id": payload["correction_id"],
            "snapshot_digest": payload["expected_snapshot_digest"],
            "previous_id": payload["expected_previous_id"],
            "proposal_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = _correction_receipt(ctx.request("POST", path, json=payload, write=True))
    return verified(
        ctx,
        lambda: _correction_receipt(ctx.request("GET", f"{path}/{payload['correction_id']}")),
        lambda row: (
            row == saved and row["id"] == payload["correction_id"]
            and row["snapshot_digest"] == payload["expected_snapshot_digest"]
            and row["line_id"] == args.line_id
            and row["previous_id"] == payload["expected_previous_id"]
        ),
    )


def _decide_payroll_correction(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_PAYROLL_APPROVE)
    require_preview_permission(ctx, PERM_PAYROLL_SENSITIVE)
    path = f"{_payroll_corrections_path(args)}/{args.correction_id}"
    current = ctx.request("GET", path)
    if current["id"] != args.correction_id or current["line_id"] != args.line_id:
        raise CLIError("The correction does not match the requested payroll line.", CONFLICT)
    if current["submitted_by_id"] == ctx.identity()["id"]:
        raise CLIError("A different actor must decide this correction.", CONFLICT)
    if current["digest"] != args.digest:
        raise CLIError("Read and confirm the exact correction digest.", CONFLICT)
    try:
        payload = PayrollCorrectionDecision.model_validate({
            "decision": args.decision, "expected_digest": args.digest
        }).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Confirm a valid correction decision and digest.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "run_id": args.run_id,
            "correction": _correction_receipt(current),
            **payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = _correction_receipt(ctx.request("POST", f"{path}/decision", json=payload, write=True))
    return verified(
        ctx,
        lambda: _correction_receipt(ctx.request("GET", path)),
        lambda row: (
            row == saved and row["status"] == args.decision
            and row["id"] == args.correction_id and row["digest"] == args.digest
        ),
    )


def _employment_changes_path(employee_id: str) -> str:
    return f"{HR}/employees/{employee_id}/employment-changes"


def _propose_employment_change(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_SENSITIVE)
    draft = load_json(Path(args.file), max_bytes=16 * 1024)
    if not isinstance(draft, dict) or "employee_revision" in draft:
        raise CLIError("Supply proposal fields only. The employee revision comes from the portal.")
    employee = ctx.request("GET", f"{HR}/employees/{args.employee_id}")
    payload = {**draft, "employee_revision": employee["record_revision"]}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "employee_id": args.employee_id, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    path = _employment_changes_path(args.employee_id)
    saved = ctx.request("POST", path, json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{path}/{saved['id']}"),
        lambda row: (
            row["status"] == "proposed"
            and row["employee_revision"] == employee["record_revision"]
            and row["updates"] == saved["updates"]
        ),
    )


def _review_or_apply_employment_change(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_SENSITIVE)
    path = f"{_employment_changes_path(args.employee_id)}/{args.change_id}"
    change = ctx.request("GET", path)
    action = args.employment_action
    if action == "decision":
        if change["status"] != "proposed":
            raise CLIError("Only a proposed change can be reviewed.", CONFLICT)
        if change["proposed_by"] == ctx.identity()["id"]:
            raise CLIError("A different HR Manager must review this change.", AUTH)
        payload = {"decision": args.decision, "reason": args.reason}
        status = args.decision
    else:
        if change["status"] != "approved":
            raise CLIError("Only an approved change can be applied.", CONFLICT)
        review_date = ctx.request(
            "GET", f"{HR}/employment-changes/due", params={"limit": 1}
        )["as_of"]
        if change["effective_date"] > review_date:
            raise CLIError("This change has not reached its effective date.", CONFLICT)
        payload = {}
        status = "applied"
    if status in {"approved", "applied"}:
        employee = ctx.request("GET", f"{HR}/employees/{args.employee_id}")
        if employee["record_revision"] != change["employee_revision"]:
            raise CLIError("The employee changed. Prepare a fresh proposal.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "change": change, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/{action}", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: row["status"] == status and row["id"] == args.change_id,
    )


def _service_request_receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in ("id", "status", "assigned_to_id", "generated_letter_id", "updated_at")
    }


def _start_service_request(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS_PROCESS)
    path = f"{HR}/requests/{args.request_id}"
    current = _service_request_receipt(ctx.request("GET", path))
    actor_id = ctx.identity()["id"]
    if current["id"] != args.request_id or current["status"] != "open":
        raise CLIError("Only an open request can enter review.", CONFLICT)
    if current["assigned_to_id"] not in {None, actor_id}:
        raise CLIError("The current assignee must start review.", CONFLICT)
    payload = {"status": "in_review", "expected_updated_at": current["updated_at"]}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "current": current, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/resolve", json=payload, write=True)
    return verified(
        ctx,
        lambda: _service_request_receipt(ctx.request("GET", path)),
        lambda row: (
            row["id"] == args.request_id
            and row["status"] == "in_review"
            and row["assigned_to_id"] == actor_id
        ),
    )


def _assign_service_request(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS_PROCESS)
    path = f"{HR}/requests/{args.request_id}"
    current = ctx.request("GET", path)
    if current["status"] not in {"open", "in_review", "approved"}:
        raise CLIError("Only an active request can be assigned.", CONFLICT)
    assignees = ctx.request("GET", f"{HR}/requests/assignees")
    if not any(row["id"] == args.assignee_id for row in assignees):
        raise CLIError("Select a current eligible HR request assignee.")
    reason = args.reason.strip()
    if not reason or len(reason) > 500:
        raise CLIError("Enter a handoff reason between 1 and 500 characters.")
    payload = {
        "assigned_to_id": args.assignee_id,
        "expected_updated_at": current["updated_at"],
        "reason": reason,
    }
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "request_id": args.request_id,
            "previous_assignee": current["assigned_to_id"],
            "proposed": {
                "assigned_to_id": args.assignee_id,
                "expected_updated_at": current["updated_at"],
            },
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if current["assigned_to_id"] == args.assignee_id:
        return Result(_service_request_receipt(current), outcome="unchanged")
    ctx.request("POST", f"{path}/assign", json=payload, write=True)
    return verified(
        ctx,
        lambda: _service_request_receipt(ctx.request("GET", path)),
        lambda row: (
            row["id"] == args.request_id
            and row["assigned_to_id"] == args.assignee_id
            and row["status"] == current["status"]
        ),
    )


def _complete_service_request(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS_PROCESS)
    path = f"{HR}/requests/{args.request_id}"
    request = ctx.request("GET", path)
    if request["status"] not in {"in_review", "approved"}:
        raise CLIError("Only a reviewed or approved request can be completed.", CONFLICT)
    if request["assigned_to_id"] not in {None, ctx.identity()["id"]}:
        raise CLIError("The current assignee must complete this request.", CONFLICT)
    response = (
        load_json(Path(args.response_file), max_bytes=12 * 1024) if args.response_file else None
    )
    if args.response_file and (
        not isinstance(response, str) or not response.strip() or len(response.strip()) > 2000
    ):
        raise CLIError("Supply a response of 1 to 2,000 characters as a JSON string.")
    payload = {"status": "completed", "expected_updated_at": request["updated_at"]}
    if response:
        payload["resolution_notes"] = response.strip()
    letter = None
    if args.letter_id:
        letter = ctx.request("GET", f"{_letters_path(request['employee_id'])}/{args.letter_id}")
        if letter["status"] != "issued":
            raise CLIError("Select a letter already issued to this employee.", CONFLICT)
        payload["generated_letter_id"] = args.letter_id
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "request_id": args.request_id,
            "response_letter_id": args.letter_id,
            "proposed": {
                key: value for key, value in payload.items() if key != "resolution_notes"
            },
            "request_sha256": sha256_json({"payload": payload, "letter": letter}),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/resolve", json=payload, write=True)
    observed = verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: (
            row["id"] == args.request_id
            and row["status"] == "completed"
            and row["generated_letter_id"] == (args.letter_id or request["generated_letter_id"])
            and (
                "resolution_notes" not in payload
                or row["resolution_notes"] == payload["resolution_notes"]
            )
        ),
    )
    return Result(_service_request_receipt(observed.data), changed=True)


def _letters_path(employee_id: str | None) -> str:
    return f"{HR}/employees/{employee_id}/letters" if employee_id else f"{HR}/me/letters"


def _draft_letter(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS_PROCESS)
    details = load_json(Path(args.file), max_bytes=64 * 1024)
    if not isinstance(details, dict) or set(details) - {"extra_vars"}:
        raise CLIError("Supply a JSON object containing only the extra_vars mapping.")
    selection = {
        "employee_id": args.employee_id,
        "template_id": args.template_id,
        **details,
    }
    preview = ctx.request("POST", f"{HR}/letters/render", json=selection)
    digest = preview.get("digest")
    if not digest:
        raise CLIError("This preview is unavailable for issuance.", CONFLICT)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "letter_id": args.letter_id,
            "preview": preview,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(
        "POST",
        f"{HR}/letters/drafts",
        json={**selection, "draft_id": args.letter_id, "expected_digest": digest},
        write=True,
    )
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{_letters_path(args.employee_id)}/{args.letter_id}"),
        lambda row: (
            row.get("id") == saved.get("id") == args.letter_id
            and row.get("body") == preview.get("body")
            and row.get("subject") == preview.get("subject")
        ),
    )


def _decide_letter(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS_PROCESS)
    path = f"{_letters_path(args.employee_id)}/{args.letter_id}"
    draft = ctx.request("GET", path)
    if not draft.get("can_decide"):
        raise CLIError("An eligible independent reviewer must decide a draft letter.", CONFLICT)
    reason = load_json(Path(args.reason_file), max_bytes=4096) if args.reason_file else None
    if args.decision == "rejected":
        if not isinstance(reason, str) or not reason.strip():
            raise CLIError("Provide the rejection reason as a JSON string in --reason-file.")
    elif reason is not None:
        raise CLIError("A reason applies only to a rejection.")
    payload = {"decision": args.decision, "reason": reason}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "letter": draft, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/decision", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: (
            row.get("status") == args.decision
            and row.get("id") == args.letter_id
            and row.get("body") == draft.get("body")
        ),
    )


def _propose_leave_policy(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_POLICY_MANAGE)
    payload = load_json(Path(args.file))
    if not isinstance(payload, dict) or payload.get("approve_immediately"):
        raise CLIError("Supply a policy draft as a JSON object for independent review.")
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "proposed": payload}, bind_actor=True
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{HR}/leave/policies", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", f"{HR}/leave/policies/{saved['id']}"),
        lambda row: row.get("status") == "draft" and row.get("code") == payload.get("code"),
    )


def _decide_leave_policy(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_POLICY_MANAGE)
    path = f"{HR}/leave/policies/{args.policy_id}"
    policy = ctx.request("GET", path)
    if policy.get("status") != "draft":
        raise CLIError("Only a draft leave policy can be reviewed.", CONFLICT)
    if policy.get("created_by_id") in {None, ctx.identity()["id"]}:
        raise CLIError("A different HR Manager must review this proposal.", AUTH)
    payload = {"decision": args.decision, "reason": args.reason}
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "policy": policy, "proposed": payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/decision", json=payload, write=True)
    return verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda row: row.get("status") == args.decision,
    )


def _leave_date_evidence_path(args: argparse.Namespace) -> str:
    return f"{HR}/leave/requests/{args.request_id}/date-evidence"


def _leave_date_evidence_receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("id", "status", "digest", "request_revision")}


def _propose_leave_date_evidence(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_MANAGE)
    path = _leave_date_evidence_path(args)
    current = ctx.request("GET", path, params={"limit": 1})
    if current["request_id"] != args.request_id or not current["can_propose"]:
        raise CLIError("This leave request is unavailable for historical date review.", CONFLICT)
    try:
        private = json.loads(read_private_bytes(args.file, max_bytes=16 * 1024))
        if not isinstance(private, dict) or private.keys() != {
            "proposal_id", "work_dates", "evidence_reference",
        }:
            raise ValueError
        payload = LeaveDateEvidenceCreate.model_validate({
            **private, "expected_revision": current["request_revision"]
        }).model_dump(mode="json")
    except ValueError:
        raise CLIError("Provide valid historical dates in an owner-only JSON file.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "request_id": args.request_id,
            "request_revision": payload["expected_revision"],
            "proposal_id": payload["proposal_id"],
            "evidence_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = _leave_date_evidence_receipt(ctx.request("POST", path, json=payload, write=True))
    detail_path = f"{path}/{payload['proposal_id']}"
    return verified(
        ctx,
        lambda: _leave_date_evidence_receipt(ctx.request("GET", detail_path)),
        lambda row: (
            row == saved and row["id"] == payload["proposal_id"]
            and row["request_revision"] == payload["expected_revision"]
        ),
    )


def _decide_leave_date_evidence(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_MANAGE)
    require_preview_permission(ctx, PERM_LEAVE_APPROVE)
    base = _leave_date_evidence_path(args)
    path = f"{base}/{args.proposal_id}"
    reviewed = ctx.request("GET", path)
    current = ctx.request("GET", base, params={"limit": 1})
    if reviewed["id"] != args.proposal_id or current["request_id"] != args.request_id:
        raise CLIError("The evidence response does not match the request.", CONFLICT)
    if not current["can_review"] or reviewed["submitted_by_id"] == ctx.identity()["id"]:
        raise CLIError("A different reviewer must decide work-date evidence.", CONFLICT)
    if reviewed["digest"] != args.digest:
        raise CLIError("Read and confirm the exact work-date evidence digest.", CONFLICT)
    if args.decision == "approved" and current["requires_payroll_correction"]:
        raise CLIError("Use payroll corrections for dates covered by approved payroll.", CONFLICT)
    try:
        payload = LeaveDateEvidenceDecision(
            decision=args.decision, expected_digest=args.digest
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Provide a valid work-date review decision and digest.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "request_id": args.request_id,
            "request_revision": current["request_revision"],
            "reviewed": _leave_date_evidence_receipt(reviewed),
            **payload,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = _leave_date_evidence_receipt(
        ctx.request("POST", f"{path}/decision", json=payload, write=True)
    )

    def readback() -> dict[str, Any]:
        row = _leave_date_evidence_receipt(ctx.request("GET", path))
        if args.decision == "approved":
            retained = ctx.request("GET", base, params={"limit": 1})
            if retained["scheduled_work_dates"] != reviewed["work_dates"]:
                raise CLIError("The reviewed work dates could not be verified on the request.")
        return row

    return verified(
        ctx, readback,
        lambda row: (
            row == saved and row["status"] == args.decision and row["digest"] == args.digest
        ),
    )


def _post_leave_accrual(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_APPROVE)
    payload = {
        "employee_id": args.employee_id,
        "leave_type_id": args.leave_type_id,
        "year": args.year,
    }
    path = f"{HR}/leave/accrual"
    if args.through_month is None:
        payload["month"] = args.month
    else:
        if args.month is None or not 1 <= args.month <= args.through_month <= 12:
            raise CLIError("Use --month and --through-month in order (1–12).")
        payload.update(start_month=args.month, end_month=args.through_month)
        path += "/catch-up"
    preview = ctx.request("POST", f"{path}/preview", json=payload)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "environment": ctx.environment,
            "period": payload,
            "accrual": preview,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if not preview.get("digest"):
        raise CLIError("This period already has a posted accrual.", CONFLICT)
    saved = ctx.request(
        "POST",
        f"{path}/apply",
        json={**payload, "expected_digest": preview["digest"]},
        write=True,
    )

    def ledger_ids(response: dict[str, Any]) -> tuple[str | None, ...]:
        return tuple(row.get("ledger_entry_id") for row in response.get("periods", [response]))

    expected_ids = ledger_ids(saved)
    return verified(
        ctx,
        lambda: ctx.request("POST", f"{path}/preview", json=payload),
        lambda row: bool(expected_ids) and all(expected_ids) and ledger_ids(row) == expected_ids,
    )


def _post_leave_rollover(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_APPROVE)
    payload = {
        "employee_id": args.employee_id,
        "leave_type_id": args.leave_type_id,
        "source_year": args.year,
    }
    path = f"{HR}/leave/rollover"
    preview = ctx.request("POST", f"{path}/preview", json=payload)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "environment": ctx.environment,
            "selection": payload,
            "rollover": preview,
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if not preview.get("digest"):
        raise CLIError("This leave year already has a posted rollover.", CONFLICT)
    saved = ctx.request(
        "POST", f"{path}/apply", json={**payload, "expected_digest": preview["digest"]}, write=True
    )
    return verified(
        ctx,
        lambda: ctx.request("POST", f"{path}/preview", json=payload),
        lambda row: bool(saved.get("receipt_id")) and row.get("receipt_id") == saved["receipt_id"],
    )


def _submit_leave(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_LEAVE_MANAGE)
    dates = {
        "leave_type_id": args.leave_type_id,
        "start_date": args.start_date,
        "end_date": args.end_date,
    }
    if args.half_day_period:
        dates.update(is_half_day=True, half_day_period=args.half_day_period)
    quote = ctx.request("GET", f"{HR}/leave/employees/{args.employee_id}/units", params=dates)
    units = quote.get("days_requested") if isinstance(quote, dict) else None
    if not isinstance(units, str):
        raise CLIError("The API returned an invalid leave quote.", CONFLICT)
    if args.days is not None:
        try:
            matches = Decimal(args.days) == Decimal(units)
        except InvalidOperation:
            raise CLIError("Expected --days to be a decimal number.") from None
        if not matches:
            raise CLIError(f"The published schedule counts {units} leave days.", CONFLICT)
    payload = {
        **dates,
        "employee_id": args.employee_id,
        "days_requested": units,
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


TIME_CREATE_SCHEMAS: dict[str, type[BaseModel]] = {
    "attendance": AttendanceEntryCreateRequest,
    "attendance/corrections": AttendanceCorrectionCreateRequest,
    "timesheets": TimesheetCreateRequest,
    "overtime": OvertimeRequestCreateRequest,
}
TIME_REVIEW_SCHEMAS: dict[str, type[BaseModel]] = {
    "attendance": AttendanceReviewRequest,
    "attendance/corrections": AttendanceCorrectionDecisionRequest,
    "timesheets": TimesheetDecisionRequest,
    "overtime": OvertimeDecisionRequest,
}


def _import_attendance(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    if args.apply and args.output:
        raise CLIError("Save a private review file with --dry-run.")
    content = read_private_bytes(args.file, max_bytes=256 * 1024)
    path = f"{HR}/attendance/imports"
    files = {"file": ("attendance.csv", content, "text/csv")}
    try:
        preview = AttendanceImportPreviewResponse.model_validate(
            ctx.request("POST", f"{path}/preview", files=files)
        )
    except ValidationError:
        raise CLIError("The API returned an invalid attendance preview.", CONFLICT) from None
    if (
        not 1 <= len(preview.items) <= 250
        or any(item.entry_id is not None for item in preview.items)
        or [item.row for item in preview.items] != list(range(2, len(preview.items) + 2))
    ):
        raise CLIError("The API returned an invalid attendance preview.", CONFLICT)
    if args.output:
        try:
            write_private_bytes(
                args.output, (preview.model_dump_json() + "\n").encode("utf-8")
            )
        except OSError:
            raise CLIError("Could not write a new private attendance review file.") from None
    invalid_rows = [item.row for item in preview.items if item.error]
    if invalid_rows or not preview.digest or not re.fullmatch(r"[a-f0-9]{64}", preview.digest):
        raise CLIError(
            "The attendance file did not pass review.",
            CONFLICT if args.apply else VALIDATION,
            data={"invalid_rows": invalid_rows},
        )
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "csv_sha256": hashlib.sha256(content).hexdigest(),
            "preview_sha256": preview.digest,
            "row_count": len(preview.items),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    response = ctx.request(
        "POST", f"{path}/apply", files=files,
        data={"expected_digest": preview.digest}, write=True,
    )
    try:
        applied = AttendanceImportPreviewResponse.model_validate(response)
        entry_ids = {item.entry_id for item in applied.items}
        if (
            applied.digest != preview.digest
            or None in entry_ids
            or len(entry_ids) != len(preview.items)
            or [item.model_copy(update={"entry_id": None}) for item in applied.items]
            != preview.items
        ):
            raise ValueError
    except ValueError:
        raise CLIError(
            "The API accepted the import, but the receipt could not be verified.",
            FAILED, changed=None,
        ) from None
    return Result(
        {
            "row_count": len(applied.items),
            "entries": [
                {"row": item.row, "entry_id": str(item.entry_id)} for item in applied.items
            ],
        },
        changed=True,
    )


def _time_record_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in ("id", "employee_id", "status", "record_revision")
        if key in row
    }


def _read_time_change(args: argparse.Namespace) -> dict[str, Any]:
    try:
        value = json.loads(read_private_bytes(args.file, max_bytes=16 * 1024))
        if not isinstance(value, dict):
            raise ValueError
    except ValueError:
        raise CLIError("Provide the time record fields in an owner-only JSON file.") from None
    return value


def _create_time_record(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    draft = _read_time_change(args)
    schema = TIME_CREATE_SCHEMAS[args.time_source]
    if (
        (args.time_source == "attendance" and draft.get("source", "manual") != "manual")
        or draft.keys() - schema.model_fields.keys()
    ):
        raise CLIError("The private file contains unsupported fields or attendance source.")
    try:
        payload = schema.model_validate(draft).model_dump(mode="json")
    except ValidationError:
        raise CLIError("The time record fields failed validation.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "employee_id": payload["employee_id"],
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    path = f"{HR}/{args.time_source}"
    saved = _time_record_summary(ctx.request("POST", path, json=payload, write=True))
    expected_status = (
        "draft" if args.time_source == "timesheets" and not payload["submit"] else "submitted"
    )
    return verified(
        ctx,
        lambda: _time_record_summary(ctx.request("GET", f"{path}/{saved['id']}")),
        lambda row: (
            row == saved and row["employee_id"] == payload["employee_id"]
            and row["status"] == expected_status
        ),
    )


def _review_time_record(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    require_preview_permission(ctx, PERM_ATTENDANCE_REVIEW)
    draft = _read_time_change(args)
    schema = TIME_REVIEW_SCHEMAS[args.time_source]
    if "expected_revision" in draft or draft.keys() - schema.model_fields.keys():
        raise CLIError("Supply review fields only. The portal provides the record revision.")
    path = f"{HR}/{args.time_source}/{args.record_id}"
    current = ctx.request("GET", path)
    if current["id"] != args.record_id:
        raise CLIError("The response does not match the requested time record.", CONFLICT)
    if "expected_revision" in schema.model_fields:
        draft["expected_revision"] = current["record_revision"]
    try:
        payload = schema.model_validate(draft).model_dump(mode="json")
    except ValidationError:
        raise CLIError("The time decision fields failed validation.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "current": _time_record_summary(current),
            "record_sha256": sha256_json(current),
            "decision": payload["decision"],
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = _time_record_summary(ctx.request("POST", f"{path}/decision", json=payload, write=True))
    return verified(
        ctx,
        lambda: _time_record_summary(ctx.request("GET", path)),
        lambda row: (
            row == saved and row["id"] == args.record_id and row["status"] == payload["decision"]
        ),
    )


def _calendar_list(ctx: Context) -> dict[str, Any]:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    result: dict[str, Any] = ctx.request("GET", f"{HR}/calendars")
    return result


def _calendar_read(ctx: Context, calendar_id: str) -> dict[str, Any]:
    for row in _calendar_list(ctx)["items"]:
        if row["id"] == calendar_id:
            return row
    raise CLIError("Work calendar was not found.", CONFLICT)


def _calendar_change(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    current = _calendar_read(ctx, args.calendar_id) if args.calendar_id else None
    schema: type[BaseModel]
    path = f"{HR}/calendars"
    method = "POST"
    if args.calendar_action == "decide":
        if args.action != "submit":
            require_preview_permission(ctx, PERM_POLICY_MANAGE)
        assert current is not None
        if args.action == "approve" and ctx.identity()["id"] in {
            current["created_by_id"], current["submitted_by_id"]
        }:
            raise CLIError("Another HR Manager must approve this calendar.", AUTH)
        schema = WorkCalendarDecisionRequest
        values = {
            "action": args.action,
            "expected_revision": current["revision"],
            "reason": args.reason,
        }
        path = f"{path}/{args.calendar_id}/decision"
        expected_status = {
            "submit": "submitted", "approve": "approved", "publish": "published",
            "return_to_draft": "draft",
        }[args.action]
    else:
        values = _read_time_change(args)
        if "expected_revision" in values:
            raise CLIError("Supply schedule fields only. The portal provides the revision.")
        schema = WorkCalendarCreateRequest
        expected_status = "draft"
        if current is not None:
            schema = WorkCalendarUpdateRequest
            values["expected_revision"] = current["revision"]
            path = f"{path}/{args.calendar_id}"
            method = "PATCH"
    try:
        payload = schema.model_validate(values, extra="forbid").model_dump(mode="json")
    except ValidationError:
        raise CLIError("The work calendar fields failed validation.") from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "calendar_id": args.calendar_id,
            "revision": current["revision"] if current is not None else None,
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request(method, path, json=payload, write=True)
    calendar_id = args.calendar_id or saved["id"]
    expected_revision = 1 if current is None else current["revision"] + 1
    return verified(
        ctx,
        lambda: _calendar_read(ctx, calendar_id),
        lambda row: (
            row == saved and row["id"] == calendar_id and row["status"] == expected_status
            and row["revision"] == expected_revision
        ),
    )


def _roster_list(args: argparse.Namespace, ctx: Context) -> Any:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    return ctx.request(
        "GET", f"{HR}/roster",
        params=query(args, "date_from", "date_to", "employee_id", "project_id", "limit", "offset"),
    )


def _roster_read(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    row: dict[str, Any] = ctx.request("GET", f"{HR}/roster/{args.allocation_id}")
    if row["id"] != args.allocation_id:
        raise CLIError("The response does not match the requested allocation.", CONFLICT)
    return row


def _roster_receipt(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "id", "employee_id", "project_id", "work_date", "calendar_id", "shift_id",
            "timezone", "starts_at", "ends_at", "planned_hours", "created_at", "cancelled_at",
        )
    }


def _roster_allocate(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_ATTENDANCE)
    try:
        payload = RosterAllocationCreateRequest.model_validate({
            "id": args.allocation_id,
            "employee_id": args.employee_id,
            "project_id": args.project_id,
            "work_date": args.work_date,
        }).model_dump(mode="json")
    except ValidationError:
        raise CLIError("Provide a valid allocation with a YYYY-MM-DD work date.") from None
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "allocation": payload}, bind_actor=True
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{HR}/roster", json=payload, write=True)
    return verified(
        ctx,
        lambda: _roster_receipt(_roster_read(args, ctx)),
        lambda row: (
            row == _roster_receipt(saved) and row["cancelled_at"] is None
            and all(row[key] == value for key, value in payload.items())
        ),
    )


def _roster_cancel(args: argparse.Namespace, ctx: Context) -> Result:
    current = _roster_read(args, ctx)
    try:
        payload = RosterCancellationRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=4096), extra="forbid"
        ).model_dump(mode="json")
    except ValidationError:
        raise CLIError('Provide an owner-only JSON file with a nonempty "reason".') from None
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "allocation": _roster_receipt(current),
            "request_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if current["cancelled_at"] is not None:
        if current["cancellation_reason"] != payload["reason"]:
            raise CLIError("This allocation has already been cancelled.", CONFLICT)
        return Result(_roster_receipt(current))
    saved = ctx.request(
        "POST", f"{HR}/roster/{args.allocation_id}/cancel", json=payload, write=True
    )
    result = verified(
        ctx,
        lambda: _roster_read(args, ctx),
        lambda row: (
            row == saved and row["cancelled_at"] is not None
            and row["cancellation_reason"] == payload["reason"]
        ),
    )
    return Result(_roster_receipt(result.data), changed=result.changed)


def _document_bytes(file: Path) -> bytes:
    try:
        with file.open("rb") as stream:
            content = stream.read(MAX_DOCUMENT_BYTES + 1)
    except OSError:
        raise CLIError("Could not open the HR document.") from None
    if not content or len(content) > MAX_DOCUMENT_BYTES:
        raise CLIError("HR document must be nonempty and no more than 60 MiB.")
    return content


def _document_record(ctx: Context, document_id: str) -> dict[str, Any]:
    doc: dict[str, Any] = ctx.request("GET", f"{HR}/documents/{document_id}")
    return doc


def _document_version(doc: dict[str, Any], number: int) -> dict[str, Any]:
    for version in doc["versions"]:
        if version["version_number"] == number:
            return version
    raise CLIError("The requested version is unavailable.", CONFLICT)


def _document_summary(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        **{
            key: doc[key]
            for key in ("id", "category", "document_type", "status", "current_version")
        },
        "versions": [
            {
                key: row[key]
                for key in (
                    "id",
                    "version_number",
                    "status",
                    "sha256_checksum",
                    "file_size",
                )
            }
            for row in doc["versions"]
        ],
    }


def _list_documents(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    listing = ctx.request(
        "GET",
        f"{HR}/documents",
        params=query(
            args, "employee_id", "candidate_id", "category", "document_type", "limit", "offset"
        ),
    )
    return {
        "items": [
            _document_summary(row) if row.get("candidate_id") else row for row in listing["items"]
        ],
        "total": listing["total"],
    }


def _upload_document(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_DOCUMENTS)
    if args.category != "ordinary":
        require_preview_permission(ctx, PERM_SENSITIVE)
    if args.candidate_id and (
        args.category != "confidential"
        or args.document_type not in {"candidate_cv", "candidate_offer"}
    ):
        raise CLIError(
            "Candidate files require confidential category and candidate_cv or candidate_offer."
        )
    if args.document_type in {"candidate_cv", "candidate_offer"} and not args.candidate_id:
        raise CLIError("A candidate is required for candidate files.")
    content = _document_bytes(args.file)
    payload = query(args, "title", "category", "employee_id", "candidate_id", "document_type")
    digest = hashlib.sha256(content).hexdigest()
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "proposed": payload,
            "sha256": digest,
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
    if args.candidate_id is None:
        return Result(document, changed=True)
    return verified(
        ctx,
        lambda: _document_summary(_document_record(ctx, document["id"])),
        lambda saved: (
            saved["versions"][0]["version_number"] == 1
            and saved["versions"][0]["sha256_checksum"] == digest
        ),
    )


def _upload_document_version(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_DOCUMENTS)
    document = _document_summary(_document_record(ctx, args.document_id))
    latest = document["versions"][0] if document["versions"] else None
    if latest and latest["status"] == "pending":
        raise CLIError("Decide the pending version first.", CONFLICT)
    number = latest["version_number"] if latest else 0
    content = _document_bytes(args.file)
    digest = hashlib.sha256(content).hexdigest()
    plan = checked_plan(
        args,
        ctx,
        {"operation": args.command_name, "document": document, "sha256": digest},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "POST",
        f"{HR}/documents/{args.document_id}/versions",
        write=True,
        data={"expected_latest_version": str(number)},
        files={"file": (args.file.name, content, "application/octet-stream")},
    )
    return verified(
        ctx,
        lambda: _document_summary(_document_record(ctx, args.document_id)),
        lambda saved: any(
            row["version_number"] == number + 1 and row["sha256_checksum"] == digest
            for row in saved["versions"]
        ),
    )


def _decide_document(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_DOCUMENTS)
    require_preview_permission(ctx, PERM_SENSITIVE)
    doc = _document_record(ctx, args.document_id)
    version = _document_version(doc, args.version)
    if version["status"] != "pending" or version["sha256_checksum"] != args.sha256:
        raise CLIError("Review the checksum of the pending file before deciding.", CONFLICT)
    if version["uploaded_by_id"] == ctx.identity()["id"]:
        raise CLIError("A different HR Manager must review this file.", AUTH)
    try:
        reason = (
            read_private_bytes(args.reason_file, max_bytes=2048).decode().strip()
            if args.reason_file
            else ""
        )
    except UnicodeDecodeError:
        raise CLIError("Supply a private UTF-8 rejection reason file.") from None
    if (
        (args.decision == "reject") != bool(reason)
        or (args.decision == "approve" and args.reason_file is not None)
        or len(reason) > 500
    ):
        raise CLIError("Supply a reason of up to 500 characters only when rejecting.")
    payload = {"decision": args.decision, "notes": reason or None}
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "document": _document_summary(doc),
            "version": args.version,
            "decision": args.decision,
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request(
        "POST",
        f"{HR}/documents/{args.document_id}/versions/{args.version}/decision",
        json=payload,
        write=True,
    )
    return verified(
        ctx,
        lambda: _document_summary(_document_record(ctx, args.document_id)),
        lambda saved: any(
            row["version_number"] == args.version
            and row["sha256_checksum"] == args.sha256
            and row["status"] == ("active" if args.decision == "approve" else "rejected")
            for row in saved["versions"]
        ),
    )


def _read_signed_hr_file(url: str, allowed_origin: str, size: int) -> bytes:
    try:
        link, origin = urlsplit(url), urlsplit(allowed_origin)
        for parsed in (link, origin):
            if (
                parsed.hostname is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.fragment
                or parsed.scheme not in {"http", "https"}
                or (
                    parsed.scheme == "http"
                    and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                )
            ):
                raise ValueError
        if (
            (link.scheme, link.hostname, link.port or (443 if link.scheme == "https" else 80))
            != (
                origin.scheme,
                origin.hostname,
                origin.port or (443 if origin.scheme == "https" else 80),
            )
            or origin.path not in {"", "/"}
            or origin.query
            or not link.path.startswith("/")
            or link.path.startswith("//")
        ):
            raise ValueError
        connect = (
            http.client.HTTPSConnection if link.scheme == "https" else http.client.HTTPConnection
        )
        hostname = link.hostname
        if hostname is None:
            raise ValueError
        connection = connect(hostname, link.port, timeout=30)
        try:
            connection.request("GET", link.path + ("?" + link.query if link.query else ""))
            response = connection.getresponse()
            if response.status != 200:
                raise CLIError("The protected file could not be retrieved.")
            return response.read(size + 1)
        finally:
            connection.close()
    except (OSError, ValueError, http.client.HTTPException):
        raise CLIError("The protected file origin or connection could not be verified.") from None


def _download_document(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    doc = _document_record(ctx, args.document_id)
    version = _document_version(doc, args.version)
    size = version["file_size"]
    if not isinstance(size, int) or not 0 < size <= MAX_DOCUMENT_BYTES:
        raise CLIError("The registered file size is unavailable.", CONFLICT)
    link = ctx.request(
        "GET",
        f"{HR}/documents/{args.document_id}/download",
        params={"version_number": args.version},
    )
    if link["document_id"] != args.document_id or link["version_number"] != args.version:
        raise CLIError("The download does not match the requested version.", CONFLICT)
    target = urlsplit(ctx.base_url)
    origin = args.object_origin or f"{target.scheme}://{target.netloc}"
    content = _read_signed_hr_file(link["download_url"], origin, size)
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != size or digest != version["sha256_checksum"]:
        raise CLIError("The downloaded file does not match the registered checksum.", CONFLICT)
    try:
        write_private_bytes(args.output, content)
    except OSError:
        raise CLIError("Could not write a new private download file.") from None
    return {"document_id": args.document_id, "version_number": args.version, "sha256": digest}


def _policy_from_list(ctx: Context, path: str, policy_id: str) -> dict[str, Any]:
    for row in ctx.request("GET", path)["items"]:
        if row["id"] == policy_id:
            return row
    raise CLIError("The policy edition is unavailable to this account.", CONFLICT)


def _policy_summary(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id", "code", "version", "effective_date", "document_id", "document_version_number",
        "supersedes_policy_id", "requires_acknowledgement", "published_at", "acknowledged_at",
        "is_current",
    )
    return {key: row[key] for key in fields if key in row}


def _publish_company_policy(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_READ)
    require_preview_permission(ctx, PERM_POLICY_MANAGE)
    try:
        request = PolicyDocumentCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024)
        )
    except ValidationError:
        raise CLIError("Provide the company policy edition in an owner-only JSON file.") from None
    payload = request.model_dump(mode="json")
    previous = None
    if request.supersedes_policy_id is not None:
        previous = _policy_summary(_policy_from_list(
            ctx, f"{HR}/policies", str(request.supersedes_policy_id)
        ))
    attachment = None
    if request.document_id is not None and request.document_version_number is not None:
        doc = _document_record(ctx, str(request.document_id))
        version = _document_version(doc, request.document_version_number)
        if (
            version["status"] != "active"
            or doc["current_version"] != request.document_version_number
            or doc["category"] != "ordinary"
            or doc["document_type"] != "policy"
            or not version["sha256_checksum"]
        ):
            raise CLIError("Select the current approved company policy file version.", CONFLICT)
        attachment = {
            "id": str(request.document_id),
            "version": request.document_version_number,
            "sha256": version["sha256_checksum"],
        }
    plan = checked_plan(
        args, ctx, {
            "operation": args.command_name,
            "code": request.code,
            "edition": request.version,
            "effective_date": request.effective_date.isoformat(),
            "supersedes": previous,
            "attachment": attachment,
            "publication_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    saved = ctx.request("POST", f"{HR}/policies", json=payload, write=True)
    return verified(
        ctx,
        lambda: _policy_summary(_policy_from_list(ctx, f"{HR}/policies", saved["id"])),
        lambda row: (
            row == _policy_summary(saved) and bool(row["published_at"])
            and all(row[key] == payload[key] for key in (
                "code", "version", "effective_date", "document_id", "document_version_number",
                "supersedes_policy_id", "requires_acknowledgement",
            ))
        ),
    )


def _acknowledge_company_policy(args: argparse.Namespace, ctx: Context) -> Result:
    path = f"{HR}/me/policies"
    policy = _policy_from_list(ctx, path, args.policy_id)
    if (policy["version"], policy["document_version_number"]) != (args.edition, args.file_version):
        raise CLIError("Confirm the exact published edition and file version.", CONFLICT)
    if not policy["requires_acknowledgement"] or (
        not policy["is_current"] and not policy["acknowledged_at"]
    ):
        raise CLIError("This edition is unavailable for acknowledgement.", CONFLICT)
    payload = PolicyAcknowledgeRequest(
        expected_version=args.edition, expected_document_version=args.file_version
    ).model_dump(mode="json")
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "policy": _policy_summary(policy), **payload},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    if policy["acknowledged_at"]:
        return Result(_policy_summary(policy), outcome="unchanged")
    saved = ctx.request("POST", f"{path}/{args.policy_id}/acknowledge", json=payload, write=True)
    return verified(
        ctx,
        lambda: _policy_summary(_policy_from_list(ctx, path, args.policy_id)),
        lambda row: (
            row["id"] == saved["policy_id"] == args.policy_id
            and row["version"] == saved["policy_version"] == args.edition
            and row["document_version_number"] == saved["document_version_number"]
            == args.file_version
            and row["acknowledged_at"] == saved["acknowledged_at"]
        ),
    )


def _download_my_company_policy(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    path = f"{HR}/me/policies"
    policy = _policy_from_list(ctx, path, args.policy_id)
    if policy["document_version_number"] is None:
        raise CLIError("This edition has no pinned policy file.", CONFLICT)
    link = ctx.request("GET", f"{path}/{args.policy_id}/download")
    if (link["document_id"], link["version_number"]) != (
        policy["document_id"], policy["document_version_number"],
    ):
        raise CLIError("The download does not match the selected policy edition.", CONFLICT)
    size, expected = link["file_size"], link["sha256_checksum"]
    if (
        not isinstance(size, int) or not 0 < size <= MAX_DOCUMENT_BYTES
        or not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None
    ):
        raise CLIError("The policy file size and checksum are unavailable.", CONFLICT)
    target = urlsplit(ctx.base_url)
    origin = args.object_origin or f"{target.scheme}://{target.netloc}"
    content = _read_signed_hr_file(link["download_url"], origin, size)
    if len(content) != size or hashlib.sha256(content).hexdigest() != expected:
        raise CLIError("The policy file does not match the registered checksum.", CONFLICT)
    try:
        write_private_bytes(args.output, content)
    except OSError:
        raise CLIError("Could not write a new private policy file.") from None
    return {"policy_id": args.policy_id, "version": policy["version"], "sha256": expected}


def _service_request_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        field: row[field]
        for field in (
            "id",
            "request_code",
            "employee_id",
            "request_type",
            "status",
            "assigned_to_id",
            "generated_document_id",
            "generated_letter_id",
            "updated_at",
        )
    }


def _list_service_requests(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    result = ctx.request(
        "GET", f"{HR}/requests", params=query(args, "employee_id", "req_status", "limit", "offset")
    )
    return {
        "items": [_service_request_summary(row) for row in result["items"]],
        "total": result["total"],
    }


def _show_service_request(args: argparse.Namespace, ctx: Context) -> dict[str, Any]:
    row = ctx.request("GET", f"{HR}/requests/{args.request_id}")
    if args.output is not None:
        try:
            write_private_bytes(args.output, (json.dumps(row, ensure_ascii=False) + "\n").encode())
        except OSError:
            raise CLIError("Could not write a new private HR request file.") from None
    return _service_request_summary(row)


def _process_service_request(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_REQUESTS)
    path = f"{HR}/requests/{args.request_id}"
    current = _service_request_summary(ctx.request("GET", path))
    action = args.request_action
    schema = (
        HrServiceRequestAssignmentRequest if action == "assign" else HrServiceRequestResolveRequest
    )
    try:
        body = json.loads(read_private_bytes(args.file, max_bytes=8192))
        if not isinstance(body, dict) or "expected_updated_at" in body:
            raise ValueError
        payload = schema.model_validate(
            {**body, "expected_updated_at": current["updated_at"]}, extra="forbid"
        ).model_dump(mode="json", exclude_unset=True)
    except ValueError:
        raise CLIError("Supply valid private HR request JSON.") from None
    if payload.get("status") in {"approved", "rejected"}:
        require_preview_permission(ctx, PERM_SENSITIVE)
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            "request": current,
            "change": {key: payload[key] for key in ("assigned_to_id", "status") if key in payload},
            "input_sha256": sha256_json(payload),
        },
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{path}/{action}", json=payload, write=True)
    expected = {
        key: value
        for key, value in payload.items()
        if key in {"assigned_to_id", "status", "resolution_notes", "generated_document_id"}
        or (key == "generated_letter_id" and value is not None)
    }
    result = verified(
        ctx,
        lambda: ctx.request("GET", path),
        lambda saved: (
            saved["id"] == current["id"]
            and all(saved.get(key) == value for key, value in expected.items())
        ),
    )
    return Result(
        _service_request_summary(result.data),
        changed=action != "assign" or current["assigned_to_id"] != payload["assigned_to_id"],
    )


def _case_metadata(case: HrCaseResponse) -> dict[str, Any]:
    return case.model_dump(
        mode="json",
        exclude={"title", "case_code", "employee_id", "details_plain", "resolution_notes"},
    )


def _case_record(ctx: Context, case_id: str) -> HrCaseResponse:
    try:
        row = HrCaseResponse.model_validate(ctx.request("GET", f"{HR}/cases/{case_id}"))
    except ValidationError:
        raise CLIError("The API returned an invalid case record.", CONFLICT) from None
    if str(row.id) != case_id or str(row.opened_by_id) != ctx.identity()["id"]:
        raise CLIError("The API did not return the requested case in your scope.", CONFLICT)
    return row


def _list_cases(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_CASES)
    try:
        listing = HrCaseListResponse.model_validate(
            ctx.request("GET", f"{HR}/cases", params=query(args, "limit", "offset"))
        )
    except ValidationError:
        raise CLIError("The API returned an invalid case list.", CONFLICT) from None
    if any(str(row.opened_by_id) != ctx.identity()["id"] for row in listing.items):
        raise CLIError("The API returned a case outside your scope.", CONFLICT)
    return Result({"items": [_case_metadata(row) for row in listing.items], "total": listing.total})


def _show_case(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_CASES)
    row = _case_record(ctx, args.case_id)
    if args.output is not None:
        try:
            write_private_bytes(args.output, (row.model_dump_json() + "\n").encode("utf-8"))
        except OSError:
            raise CLIError("Could not write a new private case file.") from None
    return Result(_case_metadata(row))


def _open_case(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_CASES)
    try:
        request = HrCaseCreateRequest.model_validate_json(
            read_private_bytes(args.file, max_bytes=64 * 1024)
        )
    except ValidationError:
        raise CLIError("Supply a valid private case file.") from None
    payload = request.model_dump(mode="json")
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "request_sha256": sha256_json(payload)},
        bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    try:
        saved = HrCaseResponse.model_validate(
            ctx.request("POST", f"{HR}/cases", json=payload, write=True)
        )
    except ValidationError:
        raise CLIError("The API did not identify the saved case.", changed=None) from None
    fields = request.model_dump(exclude={"details"})
    observed = verified(
        ctx,
        lambda: _case_record(ctx, str(saved.id)),
        lambda row: (
            row == saved
            and row.status == "open"
            and row.details_plain == request.details
            and all(getattr(row, key) == value for key, value in fields.items())
        ),
    )
    return Result(_case_metadata(observed.data), changed=observed.changed)


def _update_case(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, PERM_CASES)
    try:
        reviewed = HrCaseResponse.model_validate_json(
            read_private_bytes(args.review_file, max_bytes=96 * 1024), extra="forbid"
        )
        data = json.loads(read_private_bytes(args.file, max_bytes=64 * 1024))
        if not isinstance(data, dict) or not data.keys() <= {"status", "resolution_notes"}:
            raise ValueError
        request = HrCaseCloseRequest.model_validate(
            {**data, "expected_state_sha256": reviewed.reviewed_state_sha256()}
        )
    except ValueError:
        raise CLIError("Supply a private reviewed case and a valid status update.") from None
    case_id = str(reviewed.id)
    current = _case_record(ctx, case_id)
    if current != reviewed or current.status == "closed":
        raise CLIError("Review the current case before changing its status.", CONFLICT)
    payload = request.model_dump(mode="json", exclude_unset=True)
    if "resolution_notes" in payload:
        payload["resolution_notes"] = (request.resolution_notes or "").strip() or None
    payload["expected_state_sha256"] = reviewed.reviewed_state_sha256()
    plan = checked_plan(
        args, ctx, {"operation": args.command_name, "case_id": case_id, "status": request.status,
                    "request_sha256": sha256_json(payload)}, bind_actor=True,
    )
    if args.dry_run:
        return Result(plan, outcome="preview")
    ctx.request("POST", f"{HR}/cases/{case_id}/close", json=payload, write=True)
    expected_note = payload.get("resolution_notes", reviewed.resolution_notes)
    changed_fields = {"status", "closed_by_id", "closed_at", "resolution_notes"}
    actor_id = ctx.identity()["id"]
    observed = verified(
        ctx,
        lambda: _case_record(ctx, case_id),
        lambda row: (
            row.status == request.status
            and row.resolution_notes == expected_note
            and (request.status != "closed" or (
                str(row.closed_by_id) == actor_id and row.closed_at is not None
            ))
            and row.model_dump(exclude=changed_fields)
            == reviewed.model_dump(exclude=changed_fields)
        ),
    )
    return Result(_case_metadata(observed.data), changed=observed.changed)


def register(registry: Registry) -> None:
    p = registry.add("hr cases list", _list_cases, permission=PERM_CASES)
    p.add_argument("--limit", type=int, choices=range(1, 101), default=50)
    p.add_argument("--offset", type=int, default=0)
    p = registry.add("hr cases show", _show_case, permission=PERM_CASES)
    p.add_argument("--case-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)
    p = registry.add("hr cases open", _open_case, permission=PERM_CASES, mutates=True, preview=True)
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr cases update", _update_case, permission=PERM_CASES, mutates=True, preview=True
    )
    p.add_argument("--review-file", required=True, type=Path)
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    parser = registry.add("hr requests list", _list_service_requests, permission=PERM_REQUESTS)
    parser.add_argument("--employee-id", type=uuid_arg)
    parser.add_argument(
        "--status",
        dest="req_status",
        choices=("open", "in_review", "approved", "completed", "rejected", "cancelled"),
    )
    page(parser)
    parser = registry.add("hr requests show", _show_service_request, permission=PERM_REQUESTS)
    parser.add_argument("--request-id", required=True, type=uuid_arg)
    parser.add_argument("--output", type=Path)
    registry.add(
        "hr requests assignees",
        lambda _args, ctx: ctx.request("GET", f"{HR}/requests/assignees"),
        permission=PERM_REQUESTS,
    )
    for action in ("assign", "resolve"):
        parser = registry.add(
            f"hr requests {action}",
            _process_service_request,
            permission=PERM_REQUESTS,
            mutates=True,
            preview=True,
        )
        parser.add_argument("--request-id", required=True, type=uuid_arg)
        parser.add_argument("--file", required=True, type=Path)
        parser.set_defaults(request_action=action)
        mode(parser)
    p = registry.add("hr roster list", _roster_list, permission=PERM_ATTENDANCE)
    p.add_argument("--date-from", required=True)
    p.add_argument("--date-to", required=True)
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--project-id", type=uuid_arg)
    page(p)
    p = registry.add("hr roster show", _roster_read, permission=PERM_ATTENDANCE)
    p.add_argument("--allocation-id", type=uuid_arg, required=True)
    p = registry.add(
        "hr roster allocate", _roster_allocate, permission=PERM_ATTENDANCE,
        mutates=True, preview=True,
    )
    p.add_argument("--allocation-id", type=uuid_arg, required=True)
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--project-id", type=uuid_arg, required=True)
    p.add_argument("--work-date", required=True)
    mode(p)
    p = registry.add(
        "hr roster cancel", _roster_cancel, permission=PERM_ATTENDANCE,
        mutates=True, preview=True,
    )
    p.add_argument("--allocation-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    registry.add("hr calendars list", lambda _, c: _calendar_list(c), permission=PERM_ATTENDANCE)
    p = registry.add(
        "hr calendars show", lambda a, c: _calendar_read(c, a.calendar_id),
        permission=PERM_ATTENDANCE,
    )
    p.add_argument("--calendar-id", type=uuid_arg, required=True)
    for action in ("create", "update", "decide"):
        p = registry.add(
            f"hr calendars {action}", _calendar_change,
            permission=PERM_ATTENDANCE, mutates=True, preview=True,
        )
        p.set_defaults(calendar_action=action, calendar_id=None)
        if action != "create":
            p.add_argument("--calendar-id", type=uuid_arg, required=True)
        if action == "decide":
            p.add_argument(
                "--action", choices=("submit", "approve", "return_to_draft", "publish"),
                required=True,
            )
            p.add_argument("--reason")
        else:
            p.add_argument("--file", type=Path, required=True)
        mode(p)

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
        "hr attendance import", _import_attendance,
        permission=PERM_ATTENDANCE, mutates=True, preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--output", type=Path)
    mode(p)

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

    for label, source in (
        ("attendance", "attendance"),
        ("attendance corrections", "attendance/corrections"),
        ("timesheets", "timesheets"),
        ("overtime", "overtime"),
    ):
        if source != "attendance":
            p = registry.add(
                f"hr {label} list",
                lambda a, c: c.request(
                    "GET", f"{HR}/{a.time_source}", params=query(a, "employee_id")
                ),
                permission=PERM_ATTENDANCE,
            )
            p.set_defaults(time_source=source)
            p.add_argument("--employee-id", type=uuid_arg)
        p = registry.add(
            f"hr {label} show",
            lambda a, c: c.request("GET", f"{HR}/{a.time_source}/{a.record_id}"),
            permission=PERM_ATTENDANCE,
        )
        p.set_defaults(time_source=source)
        p.add_argument("--record-id", type=uuid_arg, required=True)

        p = registry.add(
            f"hr {label} create",
            _create_time_record,
            permission=PERM_ATTENDANCE,
            mutates=True,
            preview=True,
        )
        p.set_defaults(time_source=source)
        p.add_argument("--file", type=Path, required=True)
        mode(p)

        p = registry.add(
            f"hr {label} decide",
            _review_time_record,
            permission=f"{PERM_ATTENDANCE} and {PERM_ATTENDANCE_REVIEW}",
            mutates=True,
            preview=True,
            approval=True,
        )
        p.set_defaults(time_source=source)
        p.add_argument("--record-id", type=uuid_arg, required=True)
        p.add_argument("--file", type=Path, required=True)
        mode(p)

    p = registry.add(
        "hr documents list",
        _list_documents,
        permission=PERM_DOCUMENTS,
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--candidate-id", type=uuid_arg)
    p.add_argument("--category")
    p.add_argument("--document-type")
    page(p)

    p = registry.add(
        "hr documents upload",
        _upload_document,
        permission=PERM_DOCUMENTS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", type=Path, required=True)
    owner = p.add_mutually_exclusive_group(required=True)
    owner.add_argument("--employee-id", type=uuid_arg)
    owner.add_argument("--candidate-id", type=uuid_arg)
    p.add_argument("--title", required=True)
    p.add_argument("--document-type", required=True)
    p.add_argument(
        "--category",
        choices=["ordinary", "confidential", "identity", "medical"],
        default="ordinary",
    )
    mode(p)

    p = registry.add(
        "hr documents status",
        lambda a, c: _document_summary(_document_record(c, a.document_id)),
        permission=PERM_DOCUMENTS,
    )
    p.add_argument("--document-id", required=True, type=uuid_arg)
    p = registry.add(
        "hr documents upload-version",
        _upload_document_version,
        permission=PERM_DOCUMENTS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--document-id", required=True, type=uuid_arg)
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr documents decide",
        _decide_document,
        permission=PERM_SENSITIVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--document-id", required=True, type=uuid_arg)
    p.add_argument("--version", required=True, type=int)
    p.add_argument("--sha256", required=True)
    p.add_argument("--decision", required=True, choices=["approve", "reject"])
    p.add_argument("--reason-file", type=Path)
    mode(p)
    p = registry.add("hr documents download", _download_document, permission=PERM_DOCUMENTS)
    p.add_argument("--document-id", required=True, type=uuid_arg)
    p.add_argument("--version", required=True, type=int)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--object-origin")

    registry.add(
        "hr payroll policies list", _list_payroll_policies, permission=PERM_PAYROLL_PREPARE
    )
    p = registry.add(
        "hr payroll policies show", _show_payroll_policy, permission="payroll prepare or approve"
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path, required=True)
    for action in ("propose", "update"):
        p = registry.add(
            f"hr payroll policies {action}", _save_payroll_policy, permission=PERM_PAYROLL_PREPARE,
            mutates=True, preview=True,
        )
        p.set_defaults(policy_id=None)
        if action == "update":
            p.add_argument("--policy-id", type=uuid_arg, required=True)
        p.add_argument("--file", type=Path, required=True)
        mode(p)
    p = registry.add(
        "hr payroll policies approve", _approve_payroll_policy, permission=PERM_PAYROLL_APPROVE,
        mutates=True, preview=True, approval=True,
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)
    p.add_argument("--review-sha256", required=True)
    mode(p)

    p = registry.add(
        "hr payroll snapshot",
        lambda a, c: c.request("GET", f"{HR}/payroll/runs/{a.run_id}/snapshot"),
        permission=PERM_PAYROLL_SENSITIVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)

    registry.add(
        "hr benefits types list", _list_benefit_types, permission=PERM_PAYROLL_SENSITIVE
    )
    p = registry.add(
        "hr benefits types show", _show_benefit_type, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--benefit-type-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)
    p = registry.add(
        "hr benefits types propose", _propose_benefit_type, permission=PERM_PAYROLL_SENSITIVE,
        mutates=True, preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr benefits types approve", _approve_benefit_type, permission=PERM_PAYROLL_APPROVE,
        mutates=True, preview=True,
    )
    p.add_argument("--review-file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr benefits assignments list", _list_benefit_assignments, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--employee-id", required=True, type=uuid_arg)
    p = registry.add(
        "hr benefits assignments create", _assign_benefit, permission=PERM_PAYROLL_SENSITIVE,
        mutates=True, preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr compensation list", _list_compensation, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--employee-id", required=True, type=uuid_arg)
    p = registry.add(
        "hr compensation show", _show_compensation, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--employee-id", required=True, type=uuid_arg)
    p.add_argument("--term-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)
    for name, handler in (("propose", _propose_compensation), ("decide", _decide_compensation)):
        p = registry.add(
            f"hr compensation {name}", handler,
            permission=PERM_PAYROLL_SENSITIVE if name == "propose" else PERM_PAYROLL_APPROVE,
            mutates=True, preview=True,
        )
        p.add_argument("--file", required=True, type=Path)
        if name == "decide":
            p.add_argument("--review-file", required=True, type=Path)
        mode(p)
    p = registry.add("hr advance list", _list_advances, permission=PERM_PAYROLL_SENSITIVE)
    p.add_argument("--employee-id", required=True, type=uuid_arg)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add("hr advance show", _show_advance, permission=PERM_PAYROLL_SENSITIVE)
    p.add_argument("--advance-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)

    p = registry.add(
        "hr advance submit",
        _submit_advance,
        permission=PERM_PAYROLL_SENSITIVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    for command, action in (
        ("decide", "decision"),
        ("confirm-disbursement", "disburse"),
        ("record-repayment", "repayments"),
    ):
        p = registry.add(
            f"hr advance {command}",
            _change_advance,
            permission=PERM_PAYROLL_APPROVE,
            mutates=True,
            preview=True,
        )
        p.set_defaults(advance_action=action)
        p.add_argument("--advance-id", required=True, type=uuid_arg)
        if action == "decision":
            p.add_argument(
                "--decision", required=True, choices=["approved", "rejected", "cancelled"]
            )
        else:
            p.add_argument("--file", required=True, type=Path)
        mode(p)

    p = registry.add(
        "hr reimbursement list", _list_reimbursements, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--employee-id", required=True, type=uuid_arg)
    p.add_argument("--limit", type=int, choices=range(1, 51), default=20)
    p.add_argument("--offset", type=int, default=0)
    p = registry.add(
        "hr reimbursement show", _show_reimbursement, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--claim-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)
    p = registry.add(
        "hr reimbursement submit", _submit_reimbursement, permission=PERM_PAYROLL_SENSITIVE,
        mutates=True, preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr reimbursement decide", _decide_reimbursement, permission=PERM_PAYROLL_APPROVE,
        mutates=True, preview=True,
    )
    p.add_argument("--review-file", required=True, type=Path)
    p.add_argument("--file", required=True, type=Path)
    mode(p)
    p = registry.add(
        "hr reimbursement payable", _reimbursement_payable, permission=PERM_PAYROLL_SENSITIVE
    )
    p.add_argument("--claim-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)

    p = registry.add(
        "hr reimbursement confirm-paid",
        _confirm_reimbursement_paid,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--claim-id", required=True, type=uuid_arg)
    p.add_argument("--settlement-file", required=True, type=Path)
    mode(p)

    for source in ("time", "leave"):
        p = registry.add(
            f"hr payroll {source}-inputs", _payroll_inputs, permission=PERM_PAYROLL_PREPARE
        )
        p.set_defaults(input_source=source)
        p.add_argument("--period-id", type=uuid_arg, required=True)
        p.add_argument("--roster-file", required=True)
        p.add_argument("--output")
        p.add_argument("--sha256")

    p = registry.add(
        "hr payroll calculate",
        _calculate_payroll,
        permission=PERM_PAYROLL_PREPARE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--roster-file", required=True)
    p.add_argument("--time-sha256")
    p.add_argument("--leave-sha256")
    mode(p)

    p = registry.add(
        "hr payroll approve",
        _approve_payroll,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr payroll publish-payslips",
        _publish_payslips,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr payroll payment-export register",
        _register_payroll_export,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr payroll payment-export download",
        _download_payroll_export,
        permission=PERM_PAYROLL_APPROVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--output", required=True)

    p = registry.add(
        "hr payroll settlement summary",
        lambda a, c: c.request("GET", f"{HR}/payroll/runs/{a.run_id}/settlements"),
        permission=PERM_PAYROLL_APPROVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr payroll settlement events",
        lambda a, c: c.request(
            "GET",
            f"{HR}/payroll/runs/{a.run_id}/settlements/events",
            params=query(a, "limit", "offset", "payment_reference"),
        ),
        permission=PERM_PAYROLL_APPROVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--payment-reference", type=uuid_arg)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr payroll settlement record",
        _record_payroll_settlement,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--event-file", required=True)
    mode(p)

    p = registry.add(
        "hr payroll close",
        _close_payroll,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr payroll correction list",
        lambda a, c: c.request(
            "GET", _payroll_corrections_path(a), params=query(a, "limit", "offset")
        ),
        permission=PERM_PAYROLL_SENSITIVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--line-id", type=uuid_arg, required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr payroll correction show",
        lambda a, c: c.request("GET", f"{_payroll_corrections_path(a)}/{a.correction_id}"),
        permission=PERM_PAYROLL_SENSITIVE,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--line-id", type=uuid_arg, required=True)
    p.add_argument("--correction-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr payroll correction propose",
        _propose_payroll_correction,
        permission=PERM_PAYROLL_PREPARE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--line-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    p = registry.add(
        "hr payroll correction decide",
        _decide_payroll_correction,
        permission=PERM_PAYROLL_APPROVE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)
    p.add_argument("--line-id", type=uuid_arg, required=True)
    p.add_argument("--correction-id", type=uuid_arg, required=True)
    p.add_argument("--decision", choices=["approved", "rejected"], required=True)
    p.add_argument("--digest", required=True)
    mode(p)

    p = registry.add(
        "hr payslip list",
        lambda a, c: c.request("GET", f"{HR}/me/payslips", params=query(a, "limit", "offset")),
        permission="authenticated",
    )
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr payslip show",
        lambda a, c: c.request("GET", f"{HR}/me/payslips/{a.run_id}"),
        permission="authenticated",
    )
    p.add_argument("--run-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr employees periods",
        lambda a, c: c.request(
            "GET",
            f"{HR}/employees/{a.employee_id}/employment-periods",
            params=query(a, "limit", "offset"),
        ),
        permission=PERM_READ,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    page(p)

    p = registry.add(
        "hr employees periods-missing-start",
        lambda a, c: c.request(
            "GET", f"{HR}/employment-periods/missing-start", params=query(a, "limit", "offset")
        ),
        permission=PERM_SENSITIVE,
    )
    page(p)
    p.set_defaults(limit=20)

    p = registry.add(
        "hr employees changes due",
        lambda a, c: c.request(
            "GET", f"{HR}/employment-changes/due", params=query(a, "limit", "offset")
        ),
        permission=PERM_SENSITIVE,
    )
    page(p)
    p.set_defaults(limit=20)

    p = registry.add(
        "hr employees changes list",
        lambda a, c: c.request(
            "GET", _employment_changes_path(a.employee_id), params=query(a, "limit", "offset")
        ),
        permission=PERM_SENSITIVE,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr employees changes propose",
        _propose_employment_change,
        permission=PERM_SENSITIVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--file", required=True)
    mode(p)

    for operation, action in (("decide", "decision"), ("apply", "apply")):
        p = registry.add(
            f"hr employees changes {operation}",
            _review_or_apply_employment_change,
            permission=PERM_SENSITIVE,
            mutates=True,
            preview=True,
            approval=operation == "decide",
        )
        p.set_defaults(employment_action=action)
        p.add_argument("--employee-id", type=uuid_arg, required=True)
        p.add_argument("--change-id", type=uuid_arg, required=True)
        if operation == "decide":
            p.add_argument("--decision", choices=["approved", "rejected"], required=True)
            p.add_argument("--reason")
        mode(p)

    registry.add(
        "hr request assignees",
        lambda a, c: c.request("GET", f"{HR}/requests/assignees"),
        permission=PERM_REQUESTS_PROCESS,
    )
    p = registry.add(
        "hr request list",
        lambda a, c: c.request(
            "GET", f"{HR}/requests", params=query(a, "employee_id", "req_status", "limit", "offset")
        ),
        permission=PERM_REQUESTS_PROCESS,
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument(
        "--status",
        dest="req_status",
        choices=("open", "in_review", "approved", "completed", "rejected", "cancelled"),
    )
    page(p)
    p.set_defaults(limit=25)
    p = registry.add(
        "hr request status",
        lambda a, c: _service_request_receipt(c.request("GET", f"{HR}/requests/{a.request_id}")),
        permission=PERM_REQUESTS_PROCESS,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p = registry.add(
        "hr request start",
        _start_service_request,
        permission=PERM_REQUESTS_PROCESS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    mode(p)
    p = registry.add(
        "hr request assign",
        _assign_service_request,
        permission=PERM_REQUESTS_PROCESS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--assignee-id", type=uuid_arg, required=True)
    p.add_argument("--reason", required=True)
    mode(p)

    p = registry.add(
        "hr request complete",
        _complete_service_request,
        permission=PERM_REQUESTS_PROCESS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--letter-id", type=uuid_arg)
    p.add_argument("--response-file")
    mode(p)

    p = registry.add(
        "hr letter list",
        lambda a, c: c.request(
            "GET", _letters_path(a.employee_id), params=query(a, "limit", "offset")
        ),
        permission="authenticated",
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr letter show",
        lambda a, c: c.request("GET", f"{_letters_path(a.employee_id)}/{a.letter_id}"),
        permission="authenticated",
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--letter-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr letter draft",
        _draft_letter,
        permission=PERM_REQUESTS_PROCESS,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--template-id", type=uuid_arg, required=True)
    p.add_argument("--letter-id", type=uuid_arg, required=True)
    p.add_argument("--file", required=True)
    mode(p)

    p = registry.add(
        "hr letter decide",
        _decide_letter,
        permission=PERM_REQUESTS_PROCESS,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--letter-id", type=uuid_arg, required=True)
    p.add_argument("--decision", choices=["issued", "rejected"], required=True)
    p.add_argument("--reason-file")
    mode(p)

    registry.add(
        "hr leave policy show",
        lambda a, c: c.request("GET", f"{HR}/leave/policies"),
        permission=PERM_LEAVE_MANAGE,
    )
    registry.add(
        "hr company-policy list",
        lambda a, c: c.request("GET", f"{HR}/policies"),
        permission=PERM_READ,
    )
    p = registry.add(
        "hr company-policy publish",
        _publish_company_policy,
        permission=f"{PERM_POLICY_MANAGE} and {PERM_READ}",
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    registry.add(
        "hr my-policy list",
        lambda a, c: c.request("GET", f"{HR}/me/policies"),
        permission="authenticated",
    )
    p = registry.add(
        "hr my-policy show",
        lambda a, c: _policy_from_list(c, f"{HR}/me/policies", a.policy_id),
        permission="authenticated",
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr my-policy download", _download_my_company_policy, permission="authenticated"
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--object-origin")

    p = registry.add(
        "hr my-policy acknowledge",
        _acknowledge_company_policy,
        permission="authenticated",
        mutates=True,
        preview=True,
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)
    p.add_argument("--edition", required=True)
    p.add_argument("--file-version", type=int)
    mode(p)

    p = registry.add(
        "hr leave policy propose",
        _propose_leave_policy,
        permission=PERM_POLICY_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", required=True)
    mode(p)

    p = registry.add(
        "hr leave policy decide",
        _decide_leave_policy,
        permission=PERM_POLICY_MANAGE,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--policy-id", type=uuid_arg, required=True)
    p.add_argument("--decision", choices=["approved", "rejected"], required=True)
    p.add_argument("--reason")
    mode(p)

    p = registry.add(
        "hr leave date-evidence candidates",
        lambda a, c: c.request(
            "GET", f"{HR}/leave/date-evidence/candidates",
            params=query(a, "employee_id", "limit", "offset"),
        ),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr leave date-evidence list",
        lambda a, c: c.request(
            "GET", _leave_date_evidence_path(a), params=query(a, "limit", "offset")
        ),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)

    p = registry.add(
        "hr leave date-evidence show",
        lambda a, c: c.request("GET", f"{_leave_date_evidence_path(a)}/{a.proposal_id}"),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--proposal-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr leave date-evidence propose",
        _propose_leave_date_evidence,
        permission=PERM_LEAVE_MANAGE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    p = registry.add(
        "hr leave date-evidence decide",
        _decide_leave_date_evidence,
        permission=f"{PERM_LEAVE_MANAGE} and {PERM_LEAVE_APPROVE}",
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--request-id", type=uuid_arg, required=True)
    p.add_argument("--proposal-id", type=uuid_arg, required=True)
    p.add_argument("--decision", choices=["approved", "rejected"], required=True)
    p.add_argument("--digest", required=True)
    mode(p)

    p = registry.add(
        "hr leave accrual post",
        _post_leave_accrual,
        permission=PERM_LEAVE_APPROVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--leave-type-id", type=uuid_arg, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--month", type=int)
    p.add_argument("--through-month", type=int)
    mode(p)

    p = registry.add(
        "hr leave rollover post",
        _post_leave_rollover,
        permission=PERM_LEAVE_APPROVE,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--leave-type-id", type=uuid_arg, required=True)
    p.add_argument("--year", type=int, required=True)
    mode(p)

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
    p.add_argument("--days", help="Optional assertion against the server's calculated leave days")
    p.add_argument("--half-day-period", choices=["morning", "afternoon"])
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
            params=query(a, "req_status", "employee_id", "limit", "offset"),
        ),
        permission=PERM_LEAVE_MANAGE,
    )
    p.add_argument("--status", dest="req_status")
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--limit", type=int)
    p.add_argument("--offset", type=int)

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

    p = registry.add("hr applications status", _inspect_application, permission=PERM_RECRUITMENT)
    p.add_argument("--application-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)

    p = registry.add("hr candidates list", _list_candidates, permission=PERM_RECRUITMENT)
    p.add_argument("--code")
    p.add_argument("--search")
    page(p)

    p = registry.add("hr candidates status", _inspect_candidate, permission=PERM_RECRUITMENT)
    p.add_argument("--candidate-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path)

    p = registry.add(
        "hr candidates create",
        _create_candidate,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    p = registry.add("hr applications list", _list_applications, permission=PERM_RECRUITMENT)
    p.add_argument("--requisition-id", type=uuid_arg)
    p.add_argument("--candidate-id", type=uuid_arg)
    p.add_argument("--stage")
    page(p)

    p = registry.add(
        "hr applications create",
        _create_application,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    p = registry.add(
        "hr applications stage",
        _decide_application_stage,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--application-id", required=True, type=uuid_arg)
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    p = registry.add(
        "hr applications activity",
        lambda a, c: c.request(
            "GET",
            f"{HR}/applications/{a.application_id}/activity",
            params=query(a, "limit", "offset"),
        ),
        permission=PERM_RECRUITMENT,
    )
    p.add_argument("--application-id", required=True, type=uuid_arg)
    page(p)

    p = registry.add(
        "hr applications shortlist",
        _shortlist_application,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--application-id", required=True, type=uuid_arg)
    mode(p)

    p = registry.add(
        "hr applications withdraw",
        _withdraw_application,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--application-id", required=True, type=uuid_arg)
    p.add_argument("--decision-file", required=True)
    mode(p)

    registry.add(
        "hr correspondence templates", _correspondence_templates, permission=PERM_RECRUITMENT
    )

    p = registry.add("hr interviews list", _list_interviews, permission=PERM_RECRUITMENT)
    p.add_argument("--application-id", required=True, type=uuid_arg)

    p = registry.add(
        "hr interviews schedule",
        _schedule_interview,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    p = registry.add(
        "hr interviews update",
        _update_interview,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--application-id", required=True, type=uuid_arg)
    p.add_argument("--interview-id", required=True, type=uuid_arg)
    p.add_argument("--file", required=True, type=Path)
    mode(p)

    p = registry.add(
        "hr correspondence list",
        lambda a, c: c.request("GET", _correspondence_path(a), params=query(a, "limit", "offset")),
        permission=PERM_RECRUITMENT,
    )
    p.add_argument("--application-id", type=uuid_arg, required=True)
    page(p)

    p = registry.add(
        "hr correspondence status", _correspondence_status, permission=PERM_RECRUITMENT
    )
    p.add_argument("--application-id", type=uuid_arg, required=True)
    p.add_argument("--draft-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path)

    p = registry.add(
        "hr correspondence draft",
        _draft_correspondence,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--application-id", type=uuid_arg, required=True)
    p.add_argument("--draft-id", type=uuid_arg, required=True)
    p.add_argument("--template-id", type=uuid_arg, required=True)
    mode(p)

    p = registry.add(
        "hr correspondence decide",
        _decide_correspondence,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--application-id", type=uuid_arg, required=True)
    p.add_argument("--draft-id", type=uuid_arg, required=True)
    p.add_argument("--content-sha256", required=True)
    p.add_argument("--decision", choices=["approved", "rejected"], required=True)
    p.add_argument("--reason-file", type=Path)
    mode(p)

    p = registry.add("hr requisitions list", _list_requisitions, permission=PERM_RECRUITMENT)
    p.add_argument("--req-status")
    p.add_argument("--code")
    page(p)

    p = registry.add("hr requisitions status", _inspect_requisition, permission=PERM_RECRUITMENT)
    p.add_argument("--requisition-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path)

    p = registry.add(
        "hr requisitions create",
        _create_requisition,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    p = registry.add(
        "hr requisitions decide",
        _decide_requisition,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--requisition-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    p = registry.add("hr offers status", _inspect_offer, permission=PERM_RECRUITMENT)
    p.add_argument("--offer-id", type=uuid_arg, required=True)
    p.add_argument("--output", type=Path)

    p = registry.add("hr offers list", _list_offers, permission=PERM_RECRUITMENT)
    p.add_argument("--application-id", type=uuid_arg)
    p.add_argument("--offer-status")
    page(p)

    for action in ("draft", "reissue"):
        p = registry.add(
            f"hr offers {action}",
            _save_offer_draft,
            permission=PERM_RECRUITMENT,
            mutates=True,
            preview=True,
        )
        if action == "reissue":
            p.add_argument("--offer-id", type=uuid_arg, required=True)
        else:
            p.set_defaults(offer_id=None)
        p.add_argument("--file", type=Path, required=True)
        mode(p)

    p = registry.add(
        "hr offers decide",
        _decide_offer,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
        approval=True,
    )
    p.add_argument("--offer-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    p = registry.add(
        "hr offers convert",
        _convert_offer,
        permission=PERM_RECRUITMENT,
        mutates=True,
        preview=True,
    )
    p.add_argument("--offer-id", type=uuid_arg, required=True)
    p.add_argument("--employee-code", required=True)
    p.add_argument("--probation-days", type=int, default=0)
    mode(p)

    p = registry.add("hr onboarding list", _list_onboarding, permission=PERM_ONBOARDING)
    p.add_argument("--employee-id", type=uuid_arg)
    p.add_argument("--case-status")
    page(p)

    p = registry.add("hr onboarding status", _inspect_onboarding, permission=PERM_ONBOARDING)
    p.add_argument("--case-id", required=True, type=uuid_arg)
    p.add_argument("--output", type=Path)

    for command, handler in (
        ("create", _create_onboarding),
        ("task", _update_onboarding_task),
        ("probation", _review_probation),
    ):
        p = registry.add(
            f"hr onboarding {command}",
            handler,
            permission=PERM_ONBOARDING,
            mutates=True,
            preview=True,
            approval=command != "create",
        )
        p.add_argument("--file", type=Path, required=True)
        if command != "create":
            p.add_argument("--case-id", required=True, type=uuid_arg)
        if command == "task":
            p.add_argument("--task-id", required=True, type=uuid_arg)
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
        "hr performance list",
        lambda a, c: c.request(
            "GET", f"{HR}/performance/reviews", params=query(a, "limit", "offset")
        ),
        permission="authenticated",
    )
    page(p)
    p = registry.add(
        "hr performance show",
        lambda a, c: c.request("GET", f"{HR}/performance/reviews/{a.review_id}"),
        permission="authenticated",
    )
    p.add_argument("--review-id", type=uuid_arg, required=True)

    p = registry.add(
        "hr performance act",
        _record_performance_action,
        permission="authenticated",
        mutates=True,
        preview=True,
    )
    p.add_argument("--review-id", type=uuid_arg, required=True)
    p.add_argument("--event-id", type=uuid_arg, required=True)
    p.add_argument("--file", type=Path, required=True)
    mode(p)

    registry.add(
        "hr training courses list",
        lambda _a, c: c.request("GET", f"{HR}/training/courses"),
        permission=PERM_TRAINING,
    )
    p = registry.add(
        "hr training enrollments list",
        lambda a, c: c.request("GET", f"{HR}/training/enrollments", params=query(a, "employee_id")),
        permission=PERM_TRAINING,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p = registry.add(
        "hr training enrollments update",
        _update_training_enrollment,
        permission=PERM_TRAINING,
        mutates=True,
        preview=True,
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    p.add_argument("--enrollment-id", type=uuid_arg, required=True)
    p.add_argument("--status", required=True, choices=("in_progress", "no_show", "cancelled"))
    mode(p)
    for resource in ("courses", "enrollments"):
        p = registry.add(
            f"hr training {resource} create",
            _create_training_record,
            permission=PERM_TRAINING,
            mutates=True,
            preview=True,
        )
        p.set_defaults(training_resource=resource)
        p.add_argument("--file", type=Path, required=True)
        mode(p)

    p = registry.add(
        "hr training requirements list",
        lambda a, c: c.request(
            "GET", f"{HR}/training/requirements", params=query(a, "limit", "offset")
        ),
        permission="hr:training:manage",
    )
    page(p)
    p = registry.add(
        "hr training requirements employee",
        lambda a, c: c.request(
            "GET",
            f"{HR}/training/requirements/employees/{a.employee_id}",
            params=query(a, "limit", "offset"),
        ),
        permission="hr:training:manage",
    )
    p.add_argument("--employee-id", type=uuid_arg, required=True)
    page(p)

    p = registry.add(
        "hr training completion show",
        lambda a, c: c.request("GET", f"{HR}/training/enrollments/{a.enrollment_id}/completion"),
        permission="hr:training:manage",
    )
    p.add_argument("--enrollment-id", type=uuid_arg, required=True)
    p = registry.add(
        "hr training completion verify",
        _verify_training_completion,
        permission="hr:training:manage",
        mutates=True,
        preview=True,
    )
    p.add_argument("--enrollment-id", type=uuid_arg, required=True)
    p.add_argument("--document-id", type=uuid_arg, required=True)
    p.add_argument("--version-number", type=int, required=True)
    p.add_argument("--completed-date", required=True)
    p.add_argument("--score")
    mode(p)

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
        "hr offboarding custody list", _list_offboarding_custody, permission="authenticated"
    )
    p.add_argument("--case-id", type=uuid_arg, required=True)
    p.add_argument("--event-id", type=uuid_arg)
    p.add_argument("--area", choices=["store_inventory", "it_admin"], default="store_inventory")
    page(p)

    p = registry.add(
        "hr offboarding custody record",
        _record_offboarding_custody,
        permission="authenticated",
        mutates=True,
        preview=True,
    )
    p.add_argument("--case-id", type=uuid_arg, required=True)
    p.add_argument("--event-id", type=uuid_arg, required=True)
    p.add_argument("--kind", choices=["returned", "cleared", "waived", "flagged"], required=True)
    p.add_argument("--movement-id", type=uuid_arg)
    p.add_argument("--area", choices=["store_inventory", "it_admin"], default="store_inventory")
    p.add_argument("--device-reference")
    p.add_argument("--evidence-reference", required=True)
    mode(p)

    p = registry.add(
        "hr offboarding settlement list", _list_separation_settlements, permission="authenticated"
    )
    p.add_argument("--case-id", type=uuid_arg, required=True)
    p.add_argument("--event-id", type=uuid_arg)
    page(p)

    for action in ("propose", "review"):
        p = registry.add(
            f"hr offboarding settlement {action}",
            _record_separation_settlement,
            permission="users:manage",
            mutates=True,
            preview=True,
        )
        p.add_argument("--case-id", type=uuid_arg, required=True)
        p.add_argument("--event-id", type=uuid_arg, required=True)
        p.add_argument("--evidence-reference", required=True)
        if action == "propose":
            p.add_argument(
                "--outcome", choices=["outstanding", "settled", "nothing_due"], required=True
            )
        else:
            p.add_argument("--decision", choices=["approved", "rejected"], required=True)
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
