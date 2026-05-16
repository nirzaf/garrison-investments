from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.finance import Invoice, Payment
from app.models.project import Project
from app.models.user import User
from app.schemas.approvals import ApprovalCreateRequest
from app.schemas.finance import InvoiceCreateRequest, InvoiceUpdateRequest, PaymentCreateRequest
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    ROLE_ACCOUNTS,
    ROLE_ADMIN,
    ROLE_GENERAL_MANAGER,
    ROLE_OPERATION_MANAGER,
)
from app.utils.security import utc_now

FINANCE_ROLES = {ROLE_ADMIN, ROLE_ACCOUNTS, ROLE_OPERATION_MANAGER, ROLE_GENERAL_MANAGER}


class FinanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
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
        invoice = Invoice(
            **payload.model_dump(),
            total_amount=payload.amount + payload.tax_amount,
            status="submitted",
            payment_status="unpaid",
            created_by=actor.id,
        )
        self.session.add(invoice)
        await self.session.flush()
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
        )
        await self.audit.record(
            action="finance.invoices.created",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
        )
        await self.session.commit()
        return await self.get_invoice(invoice.id, actor)

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
        query: Select[tuple[Invoice]] = (
            select(Invoice)
            .where(Invoice.deleted_at.is_(None))
            .options(selectinload(Invoice.payments))
        )
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
        )
        if not invoice:
            raise NotFoundException("Invoice")
        return invoice

    async def update_invoice(
        self,
        invoice_id: UUID,
        payload: InvoiceUpdateRequest,
        actor: User,
    ) -> Invoice:
        invoice = await self.get_invoice(invoice_id, actor)
        if payload.status == "approved":
            invoice.approved_by = actor.id
            invoice.approved_at = utc_now()
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(invoice, key, value)
        await self.audit.record(
            action="finance.invoices.updated",
            user_id=actor.id,
            entity_type="invoices",
            entity_id=invoice.id,
            new_values=payload.model_dump(mode="json", exclude_unset=True),
        )
        await self.session.commit()
        return invoice

    async def create_payment(
        self,
        invoice_id: UUID,
        payload: PaymentCreateRequest,
        actor: User,
    ) -> Invoice:
        invoice = await self.get_invoice(invoice_id, actor)
        if payload.amount <= 0:
            raise AppException("Payment amount must be positive.", status_code=422)
        payment = Payment(**payload.model_dump(), invoice_id=invoice.id, recorded_by=actor.id)
        self.session.add(payment)
        await self.session.flush()
        paid_total = sum(payment.amount for payment in invoice.payments) + payload.amount
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
        await self.session.commit()
        return await self.get_invoice(invoice.id, actor)

    async def budget_summary(self, project_id: UUID, actor: User) -> dict[str, Decimal | UUID]:
        self.ensure_finance_access(actor)
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
                )
            )
            or 0
        )
        paid_total = Decimal(
            await self.session.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Invoice, Invoice.id == Payment.invoice_id)
                .where(Invoice.project_id == project_id, Payment.deleted_at.is_(None))
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
