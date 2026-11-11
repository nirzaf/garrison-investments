import asyncio
from contextlib import suppress
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from minio import Minio
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models.finance import Invoice, Payment
from app.models.project import Project
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.schemas.finance import InvoiceCreateRequest, InvoiceUpdateRequest, PaymentCreateRequest
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.storage_service import minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
)
from app.utils.security import utc_now

FINANCE_ROLES = {
    ROLE_ADMIN,
    ROLE_ACCOUNTS,
    ROLE_OPERATION_MANAGER,
    ROLE_GENERAL_MANAGER,
    ROLE_PROJECT_MANAGER,
}
MAX_INVOICE_FILE_SIZE = 10 * 1024 * 1024
SIGNED_URL_SECONDS = 300
ALLOWED_INVOICE_FILE_MAGIC = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py"}
# Draft and rejected invoices are not commitments against a project budget.
NON_BILLABLE_INVOICE_STATUSES = ("draft", "rejected")
# An invoice only moves forward through its workflow; nothing returns to draft, and an
# approved invoice can be rejected but never silently re-approved or resubmitted.
INVOICE_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "submitted": frozenset({"approved", "rejected"}),
    "approved": frozenset({"rejected"}),
    "rejected": frozenset({"submitted"}),
}


class FinanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.audit = AuditService(session)

    def ensure_finance_access(self, actor: User) -> None:
        if actor.role not in FINANCE_ROLES:
            raise AppException(
                "Financial records are restricted.",
                status_code=403,
                error_code="FINANCE_FORBIDDEN",
            )

    async def create_invoice(self, payload: InvoiceCreateRequest, actor: User) -> Invoice:
        self.ensure_finance_access(actor)
        if actor.role == ROLE_PROJECT_MANAGER:
            await self._ensure_project_scope(payload.project_id, actor)
        invoice = Invoice(
            **payload.model_dump(),
            total_amount=payload.amount + payload.tax_amount,
            status="submitted",
            payment_status="unpaid",
            created_by=actor.id,
        )
        self.session.add(invoice)
        await self.session.flush()
        await self._create_invoice_approval(invoice, actor)
        await self.audit.record(
            action="finance.invoices.created",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
        )
        invoice_id = invoice.id
        await self.session.commit()
        return await self.get_invoice(invoice_id, actor)

    async def _create_invoice_approval(self, invoice: Invoice, actor: User) -> None:
        await ApprovalService(self.session).create_approval(
            ApprovalCreateRequest(
                request_type="invoice",
                request_id=invoice.id,
                project_id=invoice.project_id,
                title=invoice.invoice_number,
                amount=invoice.total_amount,
                currency="USD",
                comments=invoice.notes,
            ),
            actor,
            commit=False,
            internal=True,
        )

    async def list_invoices(
        self,
        actor: User,
        *,
        project_id: UUID | None,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Invoice], int]:
        self.ensure_finance_access(actor)
        query: Select[Invoice] = (
            select(Invoice)
            .where(Invoice.deleted_at.is_(None))
            .options(selectinload(Invoice.payments))
        )
        if actor.role == ROLE_PROJECT_MANAGER:
            project_ids = await self._project_ids_for_manager(actor)
            if project_id:
                await ensure_project_access(self.session, project_id, actor)
            query = query.where(Invoice.project_id.in_(project_ids or [UUID(int=0)]))
        if project_id:
            query = query.where(Invoice.project_id == project_id)
        if status:
            query = query.where(Invoice.status == status)
        total_query = select(func.count()).select_from(
            query.with_only_columns(Invoice.id).subquery()
        )
        total = int(await self.session.scalar(total_query) or 0)
        invoices = list(
            (
                await self.session.scalars(
                    query.order_by(Invoice.invoice_date.desc()).limit(limit).offset(offset)
                )
            ).all()
        )
        return invoices, total

    async def get_invoice(self, invoice_id: UUID, actor: User) -> Invoice:
        self.ensure_finance_access(actor)
        invoice = await self.session.scalar(
            select(Invoice)
            .where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
            .options(selectinload(Invoice.payments))
            .execution_options(populate_existing=True)
        )
        if not invoice:
            raise NotFoundException("Invoice")
        await self._ensure_invoice_scope(invoice, actor)
        return invoice

    async def update_invoice(
        self,
        invoice_id: UUID,
        payload: InvoiceUpdateRequest,
        actor: User,
    ) -> Invoice:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        new_status = payload.status
        if payload.status == "approved":
            if actor.role not in {ROLE_ADMIN, ROLE_OPERATION_MANAGER}:
                raise AppException(
                    "Operation Manager approval is required before invoices are approved.",
                    status_code=403,
                    error_code="INVOICE_OPERATION_MANAGER_APPROVAL_REQUIRED",
                )
            invoice.approved_by = actor.id
            invoice.approved_at = utc_now()
        if payload.status == "rejected" and actor.role not in {
            ROLE_ADMIN,
            ROLE_OPERATION_MANAGER,
            ROLE_ACCOUNTS,
        }:
            raise AppException(
                "You cannot reject invoices.",
                status_code=403,
                error_code="INVOICE_REJECTION_FORBIDDEN",
            )
        if new_status is not None and new_status not in INVOICE_STATUS_TRANSITIONS.get(
            invoice.status, frozenset()
        ):
            raise AppException(
                f"An invoice cannot move from {invoice.status} to {new_status}.",
                status_code=409,
                error_code="INVOICE_STATUS_TRANSITION_INVALID",
            )
        changes = payload.model_dump(exclude_unset=True)
        if new_status is None:
            changes.pop("status", None)
        for key, value in changes.items():
            setattr(invoice, key, value)
        if new_status == "approved" or new_status == "rejected":
            # The invoice and its approval must agree: leaving the approval pending would
            # let a second decision from the inbox overwrite this one.
            await ApprovalService(self.session).resolve_for_entity(
                request_type="invoice",
                request_id=invoice.id,
                decision=new_status,
                actor=actor,
                comments=payload.notes,
            )
        elif new_status == "submitted":
            await self._create_invoice_approval(invoice, actor)
        await self.audit.record(
            action="finance.invoices.updated",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
            new_values=changes,
        )
        await self.session.commit()
        return invoice

    async def _get_invoice_for_update(self, invoice_id: UUID, actor: User) -> Invoice:
        self.ensure_finance_access(actor)
        invoice = await self.session.scalar(
            select(Invoice)
            .where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
            .with_for_update()
        )
        if not invoice:
            raise NotFoundException("Invoice")
        await self._ensure_invoice_scope(invoice, actor)
        return invoice

    async def upload_invoice_attachment(
        self,
        invoice_id: UUID,
        file: UploadFile,
        actor: User,
    ) -> Invoice:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        data = await file.read()
        mime_type = self._validate_file(file.filename or "invoice-attachment", data)
        extension = ".pdf" if mime_type == "application/pdf" else Path(file.filename or "").suffix
        object_key = f"finance/invoices/{invoice.id}/{uuid4().hex}{extension.lower()}"
        await asyncio.to_thread(self._upload_object, object_key, data, mime_type)
        old_key = invoice.attachment_key
        invoice.attachment_key = object_key
        invoice_id = invoice.id
        try:
            await self.audit.record(
                action="finance.invoices.attachment_uploaded",
                user_id=actor.id,
                entity_type="invoices",
                entity_id=invoice.id,
                old_values={"attachment_key": old_key},
                new_values={"attachment_key": object_key},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            with suppress(Exception):
                self._delete_object(object_key)
            raise
        return await self.get_invoice(invoice_id, actor)

    async def signed_invoice_attachment_url(self, invoice_id: UUID, actor: User) -> str:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        if not invoice.attachment_key:
            raise NotFoundException("Invoice attachment")
        await self.audit.record(
            action="finance.invoices.attachment_downloaded",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
            new_values={"attachment_key": invoice.attachment_key},
        )
        await self.session.commit()
        return minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            invoice.attachment_key,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
        )

    async def create_payment(
        self,
        invoice_id: UUID,
        payload: PaymentCreateRequest,
        actor: User,
    ) -> Invoice:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        if invoice.status != "approved":
            raise AppException(
                "Invoice must be approved before recording payments.",
                status_code=409,
                error_code="INVOICE_NOT_APPROVED",
            )
        if payload.amount <= 0:
            raise AppException("Payment amount must be positive.", status_code=422)
        if invoice.payment_status == "paid":
            raise AppException(
                "Invoice is already fully paid.",
                status_code=409,
                error_code="INVOICE_ALREADY_PAID",
            )
        # The invoice row is locked, so this balance cannot change under us mid-request.
        paid_total_existing = Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.invoice_id == invoice.id,
                    Payment.deleted_at.is_(None),
                )
            )
            or 0
        )
        outstanding = invoice.total_amount - paid_total_existing
        if payload.amount > outstanding:
            raise AppException(
                f"Payment exceeds the outstanding balance of {outstanding}.",
                status_code=409,
                error_code="PAYMENT_EXCEEDS_BALANCE",
            )
        payment = Payment(**payload.model_dump(), invoice_id=invoice.id, recorded_by=actor.id)
        self.session.add(payment)
        await self.session.flush()
        paid_total = Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.invoice_id == invoice.id,
                    Payment.deleted_at.is_(None),
                )
            )
            or 0
        )
        if paid_total <= 0:
            invoice.payment_status = "unpaid"
        elif paid_total < invoice.total_amount:
            invoice.payment_status = "partial"
        else:
            invoice.payment_status = "paid"
        await self.audit.record(
            action="finance.payments.created",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
            new_values=payload.model_dump(mode="json"),
        )
        invoice_id = invoice.id
        await self.session.commit()
        return await self.get_invoice(invoice_id, actor)

    async def budget_summary(self, project_id: UUID, actor: User) -> dict[str, Decimal | UUID]:
        self.ensure_finance_access(actor)
        if actor.role == ROLE_PROJECT_MANAGER:
            await self._ensure_project_scope(project_id, actor)
        project = await self.session.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )
        if not project:
            raise NotFoundException("Project")
        invoiced_total = Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(
                    Invoice.project_id == project_id,
                    Invoice.deleted_at.is_(None),
                    Invoice.status.notin_(NON_BILLABLE_INVOICE_STATUSES),
                )
            )
            or 0
        )
        paid_total = Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .where(
                    Invoice.project_id == project_id,
                    Payment.deleted_at.is_(None),
                    Invoice.deleted_at.is_(None),
                )
            )
            or 0
        )
        budget = Decimal(project.budget_amount or 0)
        return {
            "project_id": project_id,
            "budget_amount": budget,
            "invoiced_total": invoiced_total,
            "paid_total": paid_total,
            "remaining_budget": budget - invoiced_total,
        }

    def _validate_file(self, filename: str, data: bytes) -> str:
        if len(data) > MAX_INVOICE_FILE_SIZE:
            raise AppException("File exceeds the 10 MB limit.", status_code=413)
        if Path(filename).suffix.lower() in BLOCKED_EXTENSIONS:
            raise AppException("File type is blocked.", status_code=422)
        header = data[:32]
        for mime_type, signatures in ALLOWED_INVOICE_FILE_MAGIC.items():
            if any(signature in header for signature in signatures):
                return mime_type
        raise AppException("Unsupported invoice attachment type.", status_code=422)

    def _client(self) -> Minio:
        return minio_client(self.settings)

    def _upload_object(self, object_key: str, data: bytes, content_type: str) -> None:
        client = self._client()
        if not client.bucket_exists(self.settings.minio_bucket):
            client.make_bucket(self.settings.minio_bucket)
        client.put_object(
            self.settings.minio_bucket,
            object_key,
            BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def _delete_object(self, object_key: str) -> None:
        self._client().remove_object(self.settings.minio_bucket, object_key)

    async def _ensure_invoice_scope(self, invoice: Invoice, actor: User) -> None:
        if actor.role == ROLE_PROJECT_MANAGER:
            await self._ensure_project_scope(invoice.project_id, actor)

    async def _ensure_project_scope(self, project_id: UUID, actor: User) -> None:
        await ensure_project_access(self.session, project_id, actor)

    async def _project_ids_for_manager(self, actor: User) -> list[UUID]:
        return await accessible_project_ids(self.session, actor) or []
