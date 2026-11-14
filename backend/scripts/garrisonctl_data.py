"""Import commands and comparisons of authorized records with supplied controls."""

from __future__ import annotations

import argparse
import hashlib
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from scripts.garrisonctl_access import page, query, require_preview_permission
from scripts.garrisonctl_common import (
    CONFLICT,
    CONNECTION,
    FAILED,
    RECONCILIATION,
    CLIError,
    Context,
    Registry,
    Result,
    checked_plan,
    load_json,
    mode,
    read_private_bytes,
    uuid_arg,
)

IMPORTS = "/api/v1/imports"
FINANCE = "/api/v1/finance"
MANAGE = "users:manage"
VIEW_FINANCE = "financial:view"
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


def api_segment(value: str) -> str:
    if not re.fullmatch("[a-z][a-z0-9_]{0,63}", value):
        raise argparse.ArgumentTypeError("Expected a valid template name.")
    return value


def import_batch(ctx: Context, batch_id: str) -> dict[str, Any]:
    batch = ctx.request("GET", f"{IMPORTS}/batches/{batch_id}")
    if not isinstance(batch, dict) or batch.get("batch_id") != batch_id:
        raise CLIError("The API returned an invalid batch.", CONNECTION)
    return batch


def imports(args: argparse.Namespace, ctx: Context) -> Result:
    require_preview_permission(ctx, MANAGE)
    if args.type == "users":
        content = read_private_bytes(args.file, max_bytes=MAX_UPLOAD_BYTES)
    else:
        try:
            with args.file.open("rb") as file:
                content = file.read(MAX_UPLOAD_BYTES + 1)
        except OSError:
            raise CLIError("The import file could not be read.") from None
    if not content or len(content) > MAX_UPLOAD_BYTES:
        raise CLIError("The import file must be nonempty and at most 32 MiB.")
    name = args.file.name
    file = {"file": (name, content, "application/octet-stream")}
    path = f"{IMPORTS}/{args.type}"
    preview = ctx.request("POST", f"{path}/preview", files=file)
    if not isinstance(preview, dict) or type(preview.get("row_count")) is not int:
        raise CLIError("The API returned an invalid import preview.", CONNECTION)
    public = {"template_type": args.type, "row_count": preview["row_count"], "file_name": name}
    if preview.get("valid") is not True:
        errors = [
            {key: issue[key] for key in ("row", "field") if key in issue}
            for issue in preview.get("errors", [])
            if isinstance(issue, dict)
        ]
        raise CLIError(
            "Import preview found invalid rows.", details={"rows": errors[:100]}, data=public
        )
    if args.command_name == "imports preview":
        return Result(public, outcome="preview")
    plan = checked_plan(
        args,
        ctx,
        {
            "operation": args.command_name,
            **public,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "operation_id": args.operation_id,
        },
        bind_actor=True,
    )
    plan.pop("content_sha256")
    key = "garrisonctl-" + args.operation_id
    if args.dry_run:
        return Result({**plan, "idempotency_key": key}, outcome="preview")
    batch = ctx.request(
        "POST", f"{path}/run", files=file, write=True, headers={"Idempotency-Key": key}
    )
    if not isinstance(batch, dict) or not isinstance(batch.get("batch_id"), str):
        raise CLIError("The import response did not identify a batch.", FAILED, changed=None)
    try:
        observed = import_batch(ctx, batch["batch_id"])
    except CLIError:
        raise CLIError(
            "Import readback failed. Inspect the batch before retrying.",
            FAILED,
            changed=None,
            data={"batch_id": batch["batch_id"]},
        ) from None
    # Batch receipts can contain field messages. Select only operational counters.
    summary = observed.get("summary") or {}
    result = {
        field: observed.get(field)
        for field in (
            "batch_id",
            "template_type",
            "status",
            "row_count",
            "error_count",
        )
    }
    result.update({field: summary[field] for field in ("created", "skipped") if field in summary})
    if (
        observed.get("status") != "completed"
        or observed.get("template_type") != args.type
        or observed.get("row_count") != preview["row_count"]
        or observed.get("error_count") != 0
        or summary.get("skipped") != 0
        or summary.get("created") != preview["row_count"]
    ):
        raise CLIError(
            "The batch did not import all approved rows.", FAILED, data=result, changed=True
        )
    # The API may be returning a previously committed batch for this key.
    return Result(result, changed=None)


def paginated(ctx: Context, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    first_total: int | None = None
    while True:
        page = ctx.request("GET", path, params={**params, "offset": len(records), "limit": 200})
        if not isinstance(page, dict):
            raise CLIError("The API returned invalid pagination.", CONNECTION)
        total, items = page.get("total"), page.get("items")
        if type(total) is not int or total < 0 or total > 100_000 or not isinstance(items, list):
            raise CLIError(
                "The API returned invalid or oversized reconciliation scope.", CONNECTION
            )
        if first_total is not None and total != first_total:
            raise CLIError("Records changed during reconciliation. Run again.", CONFLICT)
        first_total = total
        records.extend(items)
        if len(records) == total:
            return records
        if not items or len(records) > total:
            raise CLIError("Records changed during reconciliation. Run again.", CONFLICT)


MONEY = frozenset(
    {
        "amount",
        "tax_amount",
        "total_amount",
        "paid_total",
        "outstanding_amount",
        "budget_amount",
        "invoiced_total",
        "remaining_budget",
        "on_hand_qty",
        "reserved_qty",
        "available_qty",
    }
)
FIELDS = {
    "users": {"role", "is_active"},
    "members": {"role_in_project"},
    "invoices": {
        "amount",
        "tax_amount",
        "total_amount",
        "paid_total",
        "outstanding_amount",
        "status",
        "payment_status",
    },
    "payments": {"amount", "payment_date", "method"},
    "budget": {"budget_amount", "invoiced_total", "paid_total", "remaining_budget"},
    "batches": {"status", "template_type", "row_count", "error_count", "created", "skipped"},
    "stock": {"on_hand_qty", "reserved_qty", "available_qty"},
}


def decimal_value(value: Any) -> Decimal:
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int)) or len(str(value)) > 80:
            raise ValueError
        number = Decimal(value)
        exponent = number.as_tuple().exponent
        if not isinstance(exponent, int) or not -30 <= exponent <= 30:
            raise ValueError
        return number
    except (ValueError, InvalidOperation):
        raise CLIError("Monetary and quantity controls must be finite decimal strings.") from None


def same_value(field: str, expected: Any, actual: Any) -> bool:
    if field in MONEY:
        return actual is not None and decimal_value(expected) == decimal_value(actual)
    return type(expected) is type(actual) and expected == actual


def compare(
    dataset: str,
    expected: Any,
    actual: list[dict[str, Any]],
    key: str,
    *,
    exact: bool = True,
) -> dict[str, Any]:
    if not isinstance(expected, dict):
        raise CLIError(f"{dataset} must map record IDs to expected fields.")
    index = {row[key]: row for row in actual}
    if len(index) != len(actual):
        raise CLIError("Records changed during reconciliation. Run again.", CONFLICT)
    matched, missing, differences = [], [], []
    for record_id, fields in expected.items():
        if not isinstance(fields, dict) or not fields or fields.keys() - FIELDS[dataset]:
            raise CLIError(f"Unsupported or empty fields in {dataset} controls.")
        for field, value in fields.items():
            if field in MONEY:
                decimal_value(value)
            elif not isinstance(value, (str, int, bool)) and value is not None:
                raise CLIError(f"Invalid field value in {dataset} controls.")
        if record_id not in index:
            missing.append(record_id)
            continue
        row = index[record_id]
        diff = [
            {"field": field, "expected": value, "actual": row.get(field)}
            for field, value in fields.items()
            if not same_value(field, value, row.get(field))
        ]
        if diff:
            differences.append({"id": record_id, "fields": diff})
        else:
            matched.append(record_id)
    return {
        "matched": sorted(matched),
        "missing": sorted(missing),
        "mismatched": differences,
        "unexpected": sorted(index.keys() - expected.keys()) if exact else [],
    }


def reconcile(args: argparse.Namespace, ctx: Context) -> Result:
    expected = load_json(args.expected_file)
    if (
        not isinstance(expected, dict)
        or not expected
        or expected.keys() - (FIELDS.keys() | {"invoice_totals"})
    ):
        raise CLIError("Provide at least one supported reconciliation dataset.")
    project_id = args.project_id
    project_sets = {"members", "invoices", "payments", "budget", "invoice_totals"}
    if expected.keys() & project_sets and not project_id:
        raise CLIError("Project controls require --project-id.")
    if expected.keys() & {"invoices", "payments", "invoice_totals"}:
        invoices = paginated(ctx, f"{FINANCE}/invoices", {"project_id": project_id})
    reports = {}
    for dataset, controls in expected.items():
        match dataset:
            case "users":
                actual = paginated(ctx, "/api/v1/users", {})
                key = "id"
            case "members":
                actual = ctx.request("GET", f"/api/v1/projects/{project_id}/members")
                key = "user_id"
            case "invoices":
                actual, key = invoices, "id"
            case "payments":
                actual, key = [p for invoice in invoices for p in invoice["payments"]], "id"
            case "budget":
                actual = [ctx.request("GET", f"{FINANCE}/projects/{project_id}/budget-summary")]
                controls, key = {project_id: controls}, "project_id"
            case "stock":
                if not args.item_id:
                    raise CLIError("Stock controls require --item-id.")
                actual = ctx.request("GET", f"/api/v1/inventory/items/{args.item_id}/stock")
                key = "location_id"
            case "batches":
                if not isinstance(controls, dict) or not controls:
                    raise CLIError("Batch controls require at least one batch ID.")
                actual, key = [], "batch_id"
                for batch_id in controls:
                    try:
                        canonical_id = uuid_arg(batch_id)
                    except argparse.ArgumentTypeError:
                        raise CLIError("Batch control keys must be UUIDs.") from None
                    if canonical_id != batch_id:
                        raise CLIError("Batch control keys must use canonical UUIDs.")
                    try:
                        batch = import_batch(ctx, batch_id)
                    except CLIError as error:
                        if error.code != CONFLICT:
                            raise
                    else:
                        summary = batch.get("summary") or {}
                        actual.append(
                            {
                                **batch,
                                **{k: summary[k] for k in ("created", "skipped") if k in summary},
                            }
                        )
            case "invoice_totals":
                allowed = FIELDS["invoices"] & MONEY
                if not isinstance(controls, dict) or not controls or controls.keys() - allowed:
                    raise CLIError("Invoice totals must contain supported monetary fields.")
                with localcontext() as context:
                    context.prec = 128
                    totals = {
                        name: str(sum((decimal_value(row[name]) for row in invoices), Decimal(0)))
                        for name in controls
                    }
                reports[dataset] = compare(
                    "invoices",
                    {"total": controls},
                    [{"id": "total", **totals}],
                    "id",
                )
                continue
            case _:
                raise CLIError("Unsupported reconciliation dataset.")
        reports[dataset] = compare(dataset, controls, actual, key)
    if any(
        report["missing"] or report["mismatched"] or report["unexpected"]
        for report in reports.values()
    ):
        raise CLIError("Reconciliation found differences.", RECONCILIATION, data=reports)
    return Result(reports)


def register(registry: Registry) -> None:
    parser = registry.add(
        "imports templates",
        lambda a, c: {
            "template_type": a.type,
            "csv": c.request("GET", f"{IMPORTS}/templates/{a.type}"),
        },
        permission=MANAGE,
    )
    parser.add_argument("--type", type=api_segment, required=True)
    for operation in ("preview", "run"):
        parser = registry.add(
            f"imports {operation}",
            imports,
            permission=MANAGE,
            mutates=operation == "run",
            preview=operation == "run",
            approval=operation == "run",
        )
        parser.add_argument("--file", type=Path, required=True)
        parser.add_argument("--type", type=api_segment, required=True)
        if operation == "run":
            parser.add_argument(
                "--operation-id",
                type=uuid_arg,
                required=True,
                help="Choose one UUID per intended import and reuse it on retry.",
            )
            mode(parser)
    registry.add(
        "imports batches", lambda a, c: c.request("GET", f"{IMPORTS}/batches"), permission=MANAGE
    )
    parser = registry.add(
        "imports status", lambda a, c: import_batch(c, a.batch_id), permission=MANAGE
    )
    parser.add_argument("--batch-id", type=uuid_arg, required=True)
    parser = registry.add(
        "finance invoices list",
        lambda a, c: c.request(
            "GET",
            f"{FINANCE}/invoices",
            params=query(a, "project_id", "status", "limit", "offset"),
        ),
        permission=VIEW_FINANCE,
    )
    parser.add_argument("--project-id", type=uuid_arg)
    parser.add_argument("--status")
    page(parser)
    parser = registry.add(
        "finance invoices show",
        lambda a, c: c.request(
            "GET",
            f"{FINANCE}/invoices/{a.invoice_id}",
        ),
        permission=VIEW_FINANCE,
    )
    parser.add_argument("--invoice-id", type=uuid_arg, required=True)
    parser = registry.add(
        "finance budget show",
        lambda a, c: c.request(
            "GET",
            f"{FINANCE}/projects/{a.project_id}/budget-summary",
        ),
        permission=VIEW_FINANCE,
    )
    parser.add_argument("--project-id", type=uuid_arg, required=True)
    parser = registry.add(
        "finance reconcile",
        reconcile,
        permission=(
            "financial:view, users:read, users:manage, projects:read or inventory:view per dataset"
        ),
    )
    parser.add_argument("--project-id", type=uuid_arg)
    parser.add_argument("--item-id", type=uuid_arg)
    parser.add_argument("--expected-file", type=Path, required=True)
