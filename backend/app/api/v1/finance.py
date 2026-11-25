from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile, status

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.business_policy import BusinessPolicyResponse
from app.config import get_settings
from app.models.user import User
from app.schemas.finance import (
    BudgetSummaryResponse,
    CurrencyReconciliationResponse,
    InvoiceAttachmentUrlResponse,
    InvoiceCreateRequest,
    InvoiceListResponse,
    InvoiceResponse,
    InvoiceSupplierOption,
    InvoiceSupplierOptionsResponse,
    InvoiceUpdateRequest,
    PaymentCreateRequest,
)
from app.services.finance_service import SIGNED_URL_SECONDS, FinanceService
from app.services.idempotency import validate_key
from app.utils.permissions import PERMISSION_FINANCIAL_VIEW

router = APIRouter(prefix="/finance", tags=["Finance"])
CanViewFinance = Annotated[User, Depends(require_permission(PERMISSION_FINANCIAL_VIEW))]


@router.get("/policy", response_model=BusinessPolicyResponse)
async def effective_business_policy(current_user: CurrentUser) -> BusinessPolicyResponse:
    return get_settings().business_policy()


@router.get("/policy/reconciliation", response_model=CurrencyReconciliationResponse)
async def currency_reconciliation(
    current_user: CurrentUser, session: DbSession
) -> CurrencyReconciliationResponse:
    return await FinanceService(session).currency_reconciliation(current_user)


@router.get("/supplier-options", response_model=InvoiceSupplierOptionsResponse)
async def list_supplier_options(
    current_user: CanViewFinance,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoiceSupplierOptionsResponse:
    suppliers, total = await FinanceService(session).list_supplier_options(
        current_user, search=search, limit=limit, offset=offset
    )
    return InvoiceSupplierOptionsResponse(
        items=[InvoiceSupplierOption(id=supplier_id, name=name) for supplier_id, name in suppliers],
        total=total,
    )


@router.get("/invoices", response_model=InvoiceListResponse)
async def list_invoices(
    current_user: CanViewFinance,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=30)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvoiceListResponse:
    service = FinanceService(session)
    invoices, total = await service.list_invoices(
        current_user,
        project_id=project_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return InvoiceListResponse(
        items=await service.invoice_responses(invoices, current_user),
        total=total,
    )


@router.post("/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    payload: InvoiceCreateRequest,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    service = FinanceService(session)
    invoice = await service.create_invoice(payload, current_user)
    return (await service.invoice_responses([invoice], current_user))[0]


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    service = FinanceService(session)
    invoice = await service.get_invoice(invoice_id, current_user)
    return (await service.invoice_responses([invoice], current_user))[0]


@router.patch("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: UUID,
    payload: InvoiceUpdateRequest,
    current_user: CanViewFinance,
    session: DbSession,
) -> InvoiceResponse:
    service = FinanceService(session)
    invoice = await service.update_invoice(invoice_id, payload, current_user)
    return (await service.invoice_responses([invoice], current_user))[0]


@router.post("/invoices/{invoice_id}/attachment", response_model=InvoiceResponse)
async def upload_invoice_attachment(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> InvoiceResponse:
    service = FinanceService(session)
    invoice = await service.upload_invoice_attachment(
        invoice_id,
        file,
        current_user,
    )
    return (await service.invoice_responses([invoice], current_user))[0]


@router.get("/invoices/{invoice_id}/attachment", response_model=InvoiceAttachmentUrlResponse)
async def get_invoice_attachment_url(
    invoice_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
    response: Response,
) -> InvoiceAttachmentUrlResponse:
    response.headers["Cache-Control"] = "no-store"
    url = await FinanceService(session).signed_invoice_attachment_url(invoice_id, current_user)
    return InvoiceAttachmentUrlResponse(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.post("/invoices/{invoice_id}/payments", response_model=InvoiceResponse)
async def create_payment(
    invoice_id: UUID,
    payload: PaymentCreateRequest,
    current_user: CanViewFinance,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> InvoiceResponse:
    service = FinanceService(session)
    invoice = await service.create_payment(
        invoice_id, payload, current_user, idempotency_key=validate_key(idempotency_key)
    )
    return (await service.invoice_responses([invoice], current_user))[0]


@router.get("/projects/{project_id}/budget-summary", response_model=BudgetSummaryResponse)
async def budget_summary(
    project_id: UUID,
    current_user: CanViewFinance,
    session: DbSession,
) -> BudgetSummaryResponse:
    summary = await FinanceService(session).budget_summary(project_id, current_user)
    return BudgetSummaryResponse.model_validate(summary)
