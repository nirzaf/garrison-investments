import asyncio
import logging
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from minio import Minio
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.business_policy import MAX_MONEY
from app.config import get_settings
from app.models.activity_log import ActivityLog
from app.models.approval import Approval
from app.models.boq_item import BoqItem
from app.models.finance import Invoice, Payment
from app.models.inventory import InventoryItem, MaterialRequest, MaterialRequestLine
from app.models.project import Project
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.schemas.finance import (
    ApprovalCurrencyCount,
    CurrencyReconciliationResponse,
    InvoiceAction,
    InvoiceCreateRequest,
    InvoiceResponse,
    InvoiceUpdateRequest,
    PaymentCreateRequest,
    PaymentResponse,
)
from app.services.approval_service import (
    APPROVAL_PENDING_STATUSES,
    OPERATING_CURRENCY_APPROVAL_TYPES,
    ApprovalService,
)
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids, ensure_project_access
from app.services.idempotency import bind, resolve_or_reserve
from app.services.storage_service import minio_client, minio_signed_url_client
from app.services.supplier_service import SupplierService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
    ROLE_PROJECT_MANAGER,
)
from app.utils.security import utc_now

logger = logging.getLogger(__name__)

FINANCE_ROLES = {
    ROLE_ADMIN,
    ROLE_ACCOUNTS,
    ROLE_OPERATION_MANAGER,
    ROLE_GENERAL_MANAGER,
    ROLE_PROJECT_MANAGER,
}
PAYMENT_IDEMPOTENCY_ROUTE = "finance.payments.create"
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
INVOICE_APPROVERS = {ROLE_ADMIN, ROLE_OPERATION_MANAGER}
INVOICE_REJECTORS = INVOICE_APPROVERS | {ROLE_ACCOUNTS}
INVOICE_CORRECTION_FIELDS = {
    "invoice_number",
    "supplier_id",
    "invoice_date",
    "due_date",
    "amount",
    "tax_amount",
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

    async def currency_reconciliation(self, actor: User) -> CurrencyReconciliationResponse:
        if actor.role != ROLE_ADMIN:
            raise AppException(
                "Currency reconciliation requires an administrator.",
                status_code=403,
                error_code="FINANCE_FORBIDDEN",
            )
        # Include soft-deleted records: their currency semantics matter during a migration.
        unlabelled = {
            "invoices": select(func.count()).select_from(Invoice),
            "payments": select(func.count()).select_from(Payment),
            "project_budgets": select(func.count()).where(Project.budget_amount.is_not(None)),
            "boq_rates": select(func.count()).select_from(BoqItem),
            "inventory_item_costs": select(func.count()).where(
                InventoryItem.unit_cost.is_not(None)
            ),
            "material_requests": select(func.count()).select_from(MaterialRequest),
            "material_request_line_costs": select(func.count()).where(
                MaterialRequestLine.unit_cost.is_not(None)
            ),
        }
        counts = (
            await self.session.execute(
                select(*(query.scalar_subquery().label(name) for name, query in unlabelled.items()))
            )
        ).mappings().one()
        approvals = await self.session.execute(
            select(Approval.request_type, Approval.currency, func.count())
            .where(Approval.request_type.in_(OPERATING_CURRENCY_APPROVAL_TYPES))
            .group_by(Approval.request_type, Approval.currency)
            .order_by(Approval.request_type, Approval.currency)
        )
        return CurrencyReconciliationResponse(
            business_currency=self.settings.business_currency,
            unlabelled_row_counts=dict(counts),
            approval_currency_counts=[
                ApprovalCurrencyCount(request_type=request_type, currency=currency, count=count)
                for request_type, currency, count in approvals
            ],
        )

    async def create_invoice(self, payload: InvoiceCreateRequest, actor: User) -> Invoice:
        self.ensure_finance_access(actor)
        await self._ensure_project_scope(payload.project_id, actor)
        project = await self.session.scalar(
            select(Project.id).where(Project.id == payload.project_id, Project.deleted_at.is_(None))
        )
        if project is None:
            raise NotFoundException("Project")
        await self._validate_supplier(payload.supplier_id)
        self._validate_dates(payload.invoice_date, payload.due_date)
        invoice = Invoice(
            **payload.model_dump(),
            total_amount=self._invoice_total(payload.amount, payload.tax_amount),
            status="submitted",
            payment_status="unpaid",
            created_by=actor.id,
        )
        self.session.add(invoice)
        await self._flush_invoice()
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

    async def list_supplier_options(
        self, actor: User, *, search: str | None, limit: int, offset: int
    ) -> tuple[list[tuple[UUID, str]], int]:
        self.ensure_finance_access(actor)
        query = select(Supplier.id, Supplier.name).where(
            Supplier.is_active.is_(True), Supplier.deleted_at.is_(None)
        )
        if search and search.strip():
            query = query.where(Supplier.name.ilike(f"%{search.strip()}%"))
        total = await self.session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await self.session.execute(
            query.order_by(func.lower(Supplier.name), Supplier.id).limit(limit).offset(offset)
        )
        return [(supplier_id, name) for supplier_id, name in rows], int(total or 0)

    async def _create_invoice_approval(self, invoice: Invoice, actor: User) -> None:
        await ApprovalService(self.session).create_approval(
            ApprovalCreateRequest(
                request_type="invoice",
                request_id=invoice.id,
                project_id=invoice.project_id,
                title=invoice.invoice_number,
                amount=invoice.total_amount,
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
                    query.order_by(Invoice.invoice_date.desc(), Invoice.id.asc())
                    .limit(limit)
                    .offset(offset)
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

    async def invoice_responses(
        self, invoices: list[Invoice], actor: User
    ) -> list[InvoiceResponse]:
        if not invoices:
            return []
        project_rows = await self.session.execute(
            select(Project.id, Project.name).where(
                Project.id.in_({item.project_id for item in invoices})
            )
        )
        project_names = {project_id: name for project_id, name in project_rows}
        supplier_rows = await self.session.execute(
            select(Supplier.id, Supplier.name).where(
                Supplier.id.in_(
                    {item.supplier_id for item in invoices if item.supplier_id is not None}
                )
            )
        )
        # Historical invoice references include inactive and previously soft-deleted suppliers.
        supplier_names = {supplier_id: name for supplier_id, name in supplier_rows}
        own_approvals = await self._own_open_approvals({item.id for item in invoices}, actor)
        items = []
        for invoice in invoices:
            payments = [
                PaymentResponse.model_validate(payment)
                for payment in sorted(
                    invoice.payments, key=lambda item: (item.payment_date, item.created_at)
                )
                if payment.deleted_at is None
            ]
            items.append(
                InvoiceResponse.model_validate(invoice).model_copy(
                    update={
                        "project_name": project_names.get(invoice.project_id),
                        "supplier_name": supplier_names.get(invoice.supplier_id)
                        if invoice.supplier_id
                        else None,
                        "payments": payments,
                        "allowed_actions": self._invoice_actions(
                            invoice,
                            actor,
                            has_payments=bool(payments),
                            own_approval=invoice.id in own_approvals,
                        ),
                    }
                )
            )
        return items

    @staticmethod
    def _invoice_actions(
        invoice: Invoice, actor: User, *, has_payments: bool, own_approval: bool
    ) -> list[InvoiceAction]:
        actions: list[InvoiceAction] = []
        if invoice.status == "rejected" and not has_payments:
            actions.extend(("correct", "resubmit"))
        if (
            invoice.status == "submitted"
            and actor.role in INVOICE_APPROVERS
            and actor.id != invoice.created_by
            and not own_approval
        ):
            actions.append("approve")
        if (
            invoice.status in {"submitted", "approved"}
            and actor.role in INVOICE_REJECTORS
            and not has_payments
        ):
            actions.append("reject")
        paid = sum(
            (payment.amount for payment in invoice.payments if payment.deleted_at is None),
            Decimal("0.00"),
        )
        if (
            invoice.status == "approved"
            and invoice.payment_status != "paid"
            and paid < invoice.total_amount
        ):
            actions.append("record_payment")
        return actions

    async def _own_open_approvals(self, invoice_ids: set[UUID], actor: User) -> set[UUID]:
        if actor.role not in INVOICE_APPROVERS:
            return set()
        return set(
            await self.session.scalars(
                select(Approval.request_id).where(
                    Approval.request_type == "invoice",
                    Approval.request_id.in_(invoice_ids),
                    Approval.submitter_id == actor.id,
                    Approval.status.in_(APPROVAL_PENDING_STATUSES),
                    Approval.deleted_at.is_(None),
                )
            )
        )

    async def update_invoice(
        self,
        invoice_id: UUID,
        payload: InvoiceUpdateRequest,
        actor: User,
    ) -> Invoice:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        if payload.expected_revision is not None and payload.expected_revision != invoice.revision:
            raise AppException(
                "This invoice changed. Compare your edits with the saved record.",
                status_code=409,
                error_code="INVOICE_REVISION_CONFLICT",
            )
        proposed = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
        new_status = payload.status
        if new_status is None:
            proposed.pop("status", None)
        if new_status == "approved":
            if actor.role not in INVOICE_APPROVERS:
                raise AppException(
                    "Operation Manager approval is required before invoices are approved.",
                    status_code=403,
                    error_code="INVOICE_OPERATION_MANAGER_APPROVAL_REQUIRED",
                )
            if actor.id == invoice.created_by or await self._own_open_approvals(
                {invoice.id}, actor
            ):
                raise AppException(
                    "Invoice submitters cannot approve their own invoice.",
                    status_code=403,
                    error_code="INVOICE_SELF_APPROVAL_FORBIDDEN",
                )
        if new_status == "rejected" and actor.role not in INVOICE_REJECTORS:
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
        changes = {key: value for key, value in proposed.items() if getattr(invoice, key) != value}
        if not changes:
            return invoice
        correcting = bool(set(changes) & INVOICE_CORRECTION_FIELDS)
        has_payments = any(payment.deleted_at is None for payment in invoice.payments)
        if correcting and invoice.status != "rejected":
            raise AppException(
                "Only rejected invoices can be corrected.",
                status_code=409,
                error_code="INVOICE_CORRECTION_REQUIRES_REJECTION",
            )
        if has_payments and (correcting or new_status in {"rejected", "submitted"}):
            raise AppException(
                "This invoice has recorded payments and requires an accounting reversal.",
                status_code=409,
                error_code="INVOICE_HAS_PAYMENTS",
            )
        if correcting and payload.expected_revision is None:
            raise AppException(
                "Reload the invoice before correcting it.",
                status_code=409,
                error_code="INVOICE_REVISION_REQUIRED",
            )
        if "supplier_id" in changes:
            await self._validate_supplier(changes["supplier_id"])
        if "invoice_date" in changes or "due_date" in changes:
            self._validate_dates(
                changes.get("invoice_date", invoice.invoice_date),
                changes.get("due_date", invoice.due_date),
            )
        if "amount" in changes or "tax_amount" in changes:
            changes["total_amount"] = self._invoice_total(
                changes.get("amount", invoice.amount), changes.get("tax_amount", invoice.tax_amount)
            )
        if new_status == "approved":
            changes.update(approved_by=actor.id, approved_at=utc_now())
        elif new_status == "submitted":
            changes.update(approved_by=None, approved_at=None)
        fields = set(changes) | {"revision"}
        old_values = InvoiceResponse.model_validate(invoice).model_dump(mode="json", include=fields)
        for key, value in changes.items():
            setattr(invoice, key, value)
        invoice.revision += 1
        await self._flush_invoice()
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
            old_values=old_values,
            new_values=InvoiceResponse.model_validate(invoice).model_dump(
                mode="json", include=fields
            ),
        )
        await self.session.commit()
        return invoice

    async def _get_invoice_for_update(self, invoice_id: UUID, actor: User) -> Invoice:
        self.ensure_finance_access(actor)
        invoice = await self.session.scalar(
            select(Invoice)
            .where(Invoice.id == invoice_id, Invoice.deleted_at.is_(None))
            .with_for_update()
            .execution_options(populate_existing=True)
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
        invoice.revision += 1
        invoice_id = invoice.id
        try:
            await self.audit.record(
                action="finance.invoices.attachment_uploaded",
                user_id=actor.id,
                entity_type="invoices",
                entity_id=invoice.id,
                old_values={"attachment_key": old_key},
                new_values={"attachment_key": object_key, "revision": invoice.revision},
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            try:
                current_key = await self.session.scalar(
                    select(Invoice.attachment_key).where(Invoice.id == invoice_id)
                )
                recorded = await self.session.scalar(
                    select(ActivityLog.id)
                    .where(
                        ActivityLog.entity_id == invoice_id,
                        ActivityLog.action == "finance.invoices.attachment_uploaded",
                        ActivityLog.new_values["attachment_key"].as_string() == object_key,
                    )
                    .limit(1)
                )
                if current_key != object_key and recorded is None:
                    await asyncio.to_thread(self._delete_object, object_key)
            except Exception:
                logger.warning("Could not clean up a failed invoice attachment upload.")
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
        *,
        idempotency_key: str | None = None,
    ) -> Invoice:
        invoice = await self._get_invoice_for_update(invoice_id, actor)
        values = payload.model_dump()
        if idempotency_key is not None:
            recorded_id = await resolve_or_reserve(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=PAYMENT_IDEMPOTENCY_ROUTE,
            )
            if recorded_id is not None:
                recorded = await self.session.get(Payment, recorded_id)
                if (
                    recorded is None
                    or recorded.invoice_id != invoice.id
                    or any(getattr(recorded, field) != value for field, value in values.items())
                ):
                    raise AppException(
                        "This payment key was already used for a different payment.",
                        status_code=409,
                        error_code="PAYMENT_REPLAY_CONFLICT",
                    )
                return invoice
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
        payment = Payment(**values, invoice_id=invoice.id, recorded_by=actor.id)
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
        invoice.revision += 1
        await self.audit.record(
            action="finance.payments.created",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
            new_values=payload.model_dump(mode="json"),
        )
        if idempotency_key is not None:
            await bind(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=PAYMENT_IDEMPOTENCY_ROUTE,
                resource_type="payment",
                resource_id=payment.id,
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

    async def _validate_supplier(self, supplier_id: UUID | None) -> None:
        if supplier_id is None:
            return
        try:
            await SupplierService(self.session).get_active_supplier(
                supplier_id, lock_selection=True
            )
        except NotFoundException as exc:
            raise AppException(
                "Select an active supplier or leave the supplier blank.",
                status_code=422,
                error_code="INVOICE_SUPPLIER_INACTIVE",
            ) from exc

    @staticmethod
    def _validate_dates(invoice_date: date, due_date: date) -> None:
        if due_date < invoice_date:
            raise AppException(
                "Due date must be on or after the invoice date.",
                status_code=422,
                error_code="INVOICE_DATE_ORDER",
            )

    @staticmethod
    def _invoice_total(amount: Decimal, tax_amount: Decimal) -> Decimal:
        total = amount + tax_amount
        if total > MAX_MONEY:
            raise AppException(
                "Invoice total exceeds the allowed amount.",
                status_code=422,
                error_code="INVOICE_AMOUNT_TOO_LARGE",
            )
        return total

    async def _flush_invoice(self) -> None:
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            if getattr(exc.orig, "sqlstate", None) != "23505":
                raise
            raise AppException(
                "This invoice number already exists.",
                status_code=409,
                error_code="INVOICE_NUMBER_CONFLICT",
            ) from exc

    def _validate_file(self, filename: str, data: bytes) -> str:
        if len(data) > MAX_INVOICE_FILE_SIZE:
            raise AppException("File exceeds the 10 MiB limit.", status_code=413)
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
