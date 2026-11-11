from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from minio import Minio
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.suppliers import SupplierCreateRequest, SupplierUpdateRequest
from app.services.audit_service import AuditService
from app.services.storage_service import minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.security import utc_now

MAX_TDS_FILE_SIZE = 30 * 1024 * 1024
SIGNED_URL_SECONDS = 300
ALLOWED_SUPPLIER_FILE_MAGIC = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py"}


class SupplierService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.audit = AuditService(session)

    async def create_supplier(self, payload: SupplierCreateRequest, actor: User) -> Supplier:
        supplier = Supplier(**payload.model_dump())
        self.session.add(supplier)
        await self.session.flush()
        await self.audit.record(
            action="suppliers.created",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            new_values=payload.model_dump(mode="json"),
        )
        await self.session.commit()
        return supplier

    async def list_suppliers(
        self,
        *,
        active: bool | None,
        compliance_status: str | None,
        search: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[Supplier], int]:
        query: Select[Supplier] = select(Supplier).where(Supplier.deleted_at.is_(None))
        if active is not None:
            query = query.where(Supplier.is_active.is_(active))
        if compliance_status:
            query = query.where(Supplier.compliance_status == compliance_status)
        if search:
            pattern = f"%{search.strip().lower()}%"
            query = query.where(
                or_(
                    func.lower(Supplier.name).like(pattern),
                    func.lower(Supplier.category).like(pattern),
                    func.lower(Supplier.tax_registration_number).like(pattern),
                )
            )
        total_query = select(func.count()).select_from(
            query.with_only_columns(Supplier.id).subquery()
        )
        suppliers = list(
            (
                await self.session.scalars(
                    query.order_by(Supplier.name.asc()).limit(limit).offset(offset)
                )
            ).all()
        )
        total = int(await self.session.scalar(total_query) or 0)
        return suppliers, total

    async def update_supplier(
        self,
        supplier_id: UUID,
        payload: SupplierUpdateRequest,
        actor: User,
    ) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        updates = payload.model_dump(exclude_unset=True)
        old_values = {key: getattr(supplier, key) for key in updates}
        for key, value in updates.items():
            setattr(supplier, key, value)
        await self.audit.record(
            action="suppliers.updated",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            old_values={
                key: str(value) if value is not None else None for key, value in old_values.items()
            },
            new_values=payload.model_dump(mode="json", exclude_unset=True),
        )
        await self.session.commit()
        return supplier

    async def deactivate_supplier(self, supplier_id: UUID, actor: User) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        supplier.is_active = False
        supplier.deleted_at = utc_now()
        await self.audit.record(
            action="suppliers.deactivated",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
        )
        await self.session.commit()
        return supplier

    async def upload_tds_document(
        self,
        supplier_id: UUID,
        file: UploadFile,
        actor: User,
    ) -> Supplier:
        supplier = await self.get_supplier(supplier_id)
        data = await file.read()
        mime_type = self._validate_file(file.filename or "tds-document", data)
        extension = ".pdf" if mime_type == "application/pdf" else Path(file.filename or "").suffix
        object_key = f"suppliers/{supplier.id}/tds/{uuid4().hex}{extension.lower()}"
        self._upload_object(object_key, data, mime_type)
        old_key = supplier.tds_document_key
        supplier.tds_document_key = object_key
        await self.audit.record(
            action="suppliers.tds_uploaded",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            old_values={"tds_document_key": old_key},
            new_values={"tds_document_key": object_key},
        )
        await self.session.commit()
        return supplier

    async def signed_tds_url(self, supplier_id: UUID, actor: User) -> str:
        supplier = await self.get_supplier(supplier_id)
        if not supplier.tds_document_key:
            raise NotFoundException("Supplier TDS document")
        await self.audit.record(
            action="suppliers.tds_downloaded",
            user_id=actor.id,
            entity_type="suppliers",
            entity_id=supplier.id,
            new_values={"tds_document_key": supplier.tds_document_key},
        )
        await self.session.commit()
        return minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            supplier.tds_document_key,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
        )

    async def get_supplier(self, supplier_id: UUID) -> Supplier:
        supplier = await self.session.scalar(
            select(Supplier).where(Supplier.id == supplier_id, Supplier.deleted_at.is_(None))
        )
        if not supplier:
            raise NotFoundException("Supplier")
        return supplier

    async def get_active_supplier(self, supplier_id: UUID) -> Supplier:
        supplier = await self.session.scalar(
            select(Supplier).where(
                Supplier.id == supplier_id,
                Supplier.is_active.is_(True),
                Supplier.deleted_at.is_(None),
            )
        )
        if not supplier:
            raise NotFoundException("Active supplier")
        return supplier

    def _validate_file(self, filename: str, data: bytes) -> str:
        if len(data) > MAX_TDS_FILE_SIZE:
            raise AppException("File exceeds the 10 MB limit.", status_code=413)
        if Path(filename).suffix.lower() in BLOCKED_EXTENSIONS:
            raise AppException("File type is blocked.", status_code=422)
        header = data[:32]
        for mime_type, signatures in ALLOWED_SUPPLIER_FILE_MAGIC.items():
            if any(signature in header for signature in signatures):
                return mime_type
        raise AppException("Unsupported supplier document type.", status_code=422)

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
