from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.finance import (
    BudgetSummaryResponse,
    InvoiceAttachmentUrlResponse,
    InvoiceCreateRequest,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceUpdateRequest,
    PaymentCreateRequest,
)
from app.services.finance_service import SIGNED_URL_SECONDS, FinanceService
from app.utils.permissions import PERMISSION_FINANCIAL_VIEW

router = APIRouter(prefix="/finance", tags=["Finance"])
CanViewFinance = Annotated[User, Depends(require_permission(PERMISSION_FINANCIAL_VIEW))]


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    current_user: CanViewFinance,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoiceListResponse:
    invoices, total = await FinanceService(session).list_invoices(
        current_user,
        project_id=project_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return InvoiceListResponse(
        items=[InvoiceResponse.model_validate(invoice) for invoice in invoices],
        total=total,
    )


@router.post("/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreateRequest,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    invoice = await FinanceService(session).create_invoice(payload, current_user)
    return InvoiceResponse.model_validate(invoice)


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    invoice = await FinanceService(session).get_invoice(invoice_id, current_user)
    return InvoiceResponse.model_validate(invoice)


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    payload: InvoiceUpdateRequest,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    invoice = await FinanceService(session).update_invoice(invoice_id, payload, current_user)
    return InvoiceResponse.model_validate(invoice)


@router.post("/invoices/{invoice_id}/attachment", response_model=InvoiceResponse)
async def upload_invoice_attachment(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> InvoiceResponse:
    invoice = await FinanceService(session).upload_invoice_attachment(
        invoice_id,
        file,
        current_user,
    )
    return InvoiceResponse.model_validate(invoice)


@router.get("/invoices/{invoice_id}/attachment", response_model=InvoiceAttachmentUrlResponse)
async def get_invoice_attachment_url(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceAttachmentUrlResponse:
    url = await FinanceService(session).signed_invoice_attachment_url(invoice_id, current_user)
    return InvoiceAttachmentUrlResponse(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceResponse)
async def create_payment(
    invoice_id: UUID,
    payload: PaymentCreateRequest,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    invoice = await FinanceService(session).create_payment(invoice_id, payload, current_user)
    return InvoiceResponse.model_validate(invoice)


@router.get("/projects/{project_id}/budget-summary", response_model=BudgetSummaryResponse)
async def budget_summary(
    project_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
) -> BudgetSummaryResponse:
    summary = await FinanceService(session).budget_summary(project_id, current_user)
    return BudgetSummaryResponse.model_validate(summary)
