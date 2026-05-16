from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.suppliers import (
    SupplierCreateRequest,
    SupplierDocumentUrlResponse,
    SupplierListResponse,
    SupplierResponse,
    SupplierUpdateRequest,
)
from app.services.supplier_service import SIGNED_URL_SECONDS, SupplierService
from app.utils.permissions import PERMISSION_SUPPLIERS_MANAGE

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])

CanManageSuppliers = Annotated[User, Depends(require_permission(PERMISSION_SUPPLIERS_MANAGE))]


@router.get("", response_model=SupplierListResponse)
async def list_suppliers(
    _: CanManageSuppliers,
    session: DbSession,
    active: Annotated[bool | None, Query()] = None,
    compliance_status: Annotated[str | None, Query(max_length=30)] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupplierListResponse:
    suppliers, total = await SupplierService(session).list_suppliers(
        active=active,
        compliance_status=compliance_status,
        search=search,
        limit=limit,
        offset=offset,
    )
    return SupplierListResponse(
        items=[SupplierResponse.model_validate(supplier) for supplier in suppliers],
        total=total,
    )


@router.post("", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreateRequest,
    current_user: CanManageSuppliers,
    session: DbSession,
) -> SupplierResponse:
    supplier = await SupplierService(session).create_supplier(payload, current_user)
    return SupplierResponse.model_validate(supplier)


@router.patch("/{supplier_id}", response_model=SupplierResponse)
async def update_supplier(
    supplier_id: UUID,
    payload: SupplierUpdateRequest,
    current_user: CanManageSuppliers,
    session: DbSession,
) -> SupplierResponse:
    supplier = await SupplierService(session).update_supplier(supplier_id, payload, current_user)
    return SupplierResponse.model_validate(supplier)


@router.post("/{supplier_id}/tds-document", response_model=SupplierResponse)
async def upload_tds_document(
    supplier_id: UUID,
    current_user: CanManageSuppliers,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> SupplierResponse:
    supplier = await SupplierService(session).upload_tds_document(
        supplier_id,
        file,
        current_user,
    )
    return SupplierResponse.model_validate(supplier)


@router.get("/{supplier_id}/tds-document", response_model=SupplierDocumentUrlResponse)
async def get_tds_document_url(
    supplier_id: UUID,
    current_user: CanManageSuppliers,
    session: DbSession,
) -> SupplierDocumentUrlResponse:
    url = await SupplierService(session).signed_tds_url(supplier_id, current_user)
    return SupplierDocumentUrlResponse(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.delete("/{supplier_id}", response_model=SupplierResponse)
async def deactivate_supplier(
    supplier_id: UUID,
    current_user: CanManageSuppliers,
    session: DbSession,
) -> SupplierResponse:
    supplier = await SupplierService(session).deactivate_supplier(supplier_id, current_user)
    return SupplierResponse.model_validate(supplier)
