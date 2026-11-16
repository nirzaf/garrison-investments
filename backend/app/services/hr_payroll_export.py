"""Create and reproduce the approved, bank-independent payroll handoff."""

import csv
import hashlib
from decimal import Decimal
from io import StringIO
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr import HrPayrollExport, HrPayrollPeriod, HrPayrollRun
from app.models.user import User
from app.schemas.hr import PayrollExportConfirmRequest, PayrollExportPreview, PayrollExportReceipt
from app.services.audit_service import AuditService
from app.services.hr_payroll_snapshot import (
    _line_amounts,
    _locked_run,
    _stored_snapshot,
    get_payroll_run,
)
from app.utils.exceptions import AppException, NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_HR_PAYROLL_APPROVE,
    PERMISSION_HR_PAYROLL_SENSITIVE,
    ensure_permission,
)
from app.utils.security import utc_now

FORMAT_VERSION = 1


def _ensure_export_access(actor: User) -> None:
    ensure_permission(actor, PERMISSION_HR_PAYROLL_APPROVE)
    ensure_permission(actor, PERMISSION_HR_PAYROLL_SENSITIVE)


async def _export_material(
    session: AsyncSession, run: HrPayrollRun
) -> tuple[PayrollExportPreview, bytes]:
    period = await session.get(HrPayrollPeriod, run.payroll_period_id)
    if (
        run.status != "approved"
        or run.approved_at is None
        or not run.snapshot_digest
        or period is None
        or period.status != "locked"
    ):
        raise AppException(
            "Only an approved and locked payroll snapshot can be exported.", status_code=409
        )
    snapshot, lines = await _stored_snapshot(session, run)
    if (snapshot["period_start"], snapshot["period_end"], snapshot["pay_date"]) != (
        period.period_start.isoformat(),
        period.period_end.isoformat(),
        period.pay_date.isoformat(),
    ):
        raise AppException(
            "The payroll period differs from the approved snapshot.", status_code=409
        )
    currency = snapshot["currency"]
    if (
        not isinstance(currency, str)
        or len(currency) != 3
        or not (currency.isascii() and currency.isalpha() and currency.isupper())
    ):
        raise AppException("The approved export currency is invalid.", status_code=409)
    gross = deductions = net = Decimal("0.00")
    payments = 0
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("payment_reference", "currency", "net_amount"))
    for line in sorted(lines, key=lambda row: row.id):
        amounts = _line_amounts(line)
        if amounts["gross"] - amounts["deductions"] != amounts["net"]:
            raise AppException("The approved payroll lines do not balance.", status_code=409)
        gross += amounts["gross"]
        deductions += amounts["deductions"]
        net += amounts["net"]
        if amounts["net"] > 0:
            writer.writerow((str(line.id), currency, format(amounts["net"], ".2f")))
            payments += 1
    if gross - deductions != net:
        raise AppException("The approved payroll totals do not balance.", status_code=409)
    content = output.getvalue().encode("utf-8")
    preview = PayrollExportPreview(
        run_id=run.id,
        snapshot_digest=run.snapshot_digest,
        csv_sha256=hashlib.sha256(content).hexdigest(),
        format_version=FORMAT_VERSION,
        currency=currency,
        pay_date=period.pay_date,
        payment_count=payments,
        zero_net_count=len(lines) - payments,
        gross=gross,
        deductions=deductions,
        net=net,
    )
    return preview, content


def _verify_receipt(receipt: HrPayrollExport, preview: PayrollExportPreview) -> None:
    if (receipt.snapshot_digest, receipt.csv_sha256, receipt.format_version) != (
        preview.snapshot_digest,
        preview.csv_sha256,
        preview.format_version,
    ):
        raise AppException(
            "The original payroll export can no longer be reproduced.", status_code=409
        )


async def preview_payroll_export(
    session: AsyncSession, run_id: UUID, actor: User
) -> PayrollExportPreview:
    _ensure_export_access(actor)
    run = await get_payroll_run(session, run_id)
    preview, _ = await _export_material(session, run)
    receipt = await session.get(HrPayrollExport, run_id)
    if receipt is not None:
        _verify_receipt(receipt, preview)
        preview.receipt = PayrollExportReceipt.model_validate(receipt)
    await AuditService(session).record(
        action="hr.payroll_export.previewed",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run_id,
    )
    await session.commit()
    return preview


async def register_payroll_export(
    session: AsyncSession, run_id: UUID, payload: PayrollExportConfirmRequest, actor: User
) -> HrPayrollExport:
    _ensure_export_access(actor)
    run, _ = await _locked_run(session, run_id)
    preview, _ = await _export_material(session, run)
    if run.approved_by_id != actor.id or run.prepared_by_id == actor.id:
        raise PermissionDeniedException("register this payroll export")
    if (payload.expected_snapshot_digest, payload.expected_csv_sha256) != (
        preview.snapshot_digest,
        preview.csv_sha256,
    ):
        raise AppException("Review and confirm the current export preview.", status_code=409)
    existing = await session.get(HrPayrollExport, run_id)
    if existing is not None:
        _verify_receipt(existing, preview)
        return existing
    if preview.payment_count == 0:
        raise AppException("No positive payroll amounts are available for export.", status_code=409)
    receipt = HrPayrollExport(
        run_id=run.id,
        exported_by_id=actor.id,
        snapshot_digest=preview.snapshot_digest,
        csv_sha256=preview.csv_sha256,
        format_version=preview.format_version,
        exported_at=utc_now(),
    )
    session.add(receipt)
    await AuditService(session).record(
        action="hr.payroll_export.registered",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
        new_values={"csv_sha256": preview.csv_sha256, "payment_count": preview.payment_count},
    )
    await session.commit()
    return receipt


async def download_payroll_export(
    session: AsyncSession, run_id: UUID, actor: User
) -> tuple[bytes, str]:
    _ensure_export_access(actor)
    receipt = await session.get(HrPayrollExport, run_id)
    if receipt is None:
        raise NotFoundException("Registered payroll export")
    run = await get_payroll_run(session, run_id)
    preview, content = await _export_material(session, run)
    _verify_receipt(receipt, preview)
    await AuditService(session).record(
        action="hr.payroll_export.downloaded",
        user_id=actor.id,
        entity_type="hr_payroll_runs",
        entity_id=run.id,
        new_values={"csv_sha256": receipt.csv_sha256},
    )
    await session.commit()
    return content, receipt.csv_sha256
