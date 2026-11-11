import asyncio
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from minio import Minio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.document import Document, DocumentVersion
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.services.audit_service import AuditService
from app.services.authorization import (
    document_scope_filter,
    ensure_document_access,
    ensure_project_access,
)
from app.services.notification_service import NotificationService
from app.services.storage_service import minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.links import append_link, document_url
from app.utils.permissions import ROLE_ADMIN, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER
from app.utils.security import utc_now

MAX_DOCUMENT_SIZE = 60 * 1024 * 1024
SIGNED_URL_SECONDS = 300
ALLOWED_DOCUMENT_MAGIC = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py"}


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.documents = DocumentRepository(session)
        self.audit = AuditService(session)
        self.notifications = NotificationService(session)

    async def upload_document(
        self,
        *,
        title: str,
        document_type: str,
        project_id: UUID | None,
        expiry_date: date | None,
        file: UploadFile,
        actor: User,
    ) -> Document:
        data = await file.read()
        mime_type = self._validate_file(file.filename or "document", data)
        if project_id is not None:
            await ensure_project_access(self.session, project_id, actor)
        document = await self.documents.add_document(
            Document(
                title=title,
                document_type=document_type,
                project_id=project_id,
                status="pending_approval",
                active_version=None,
                metadata_json={},
                expiry_date=expiry_date,
                uploaded_by=actor.id,
            )
        )
        version = await self._store_version(
            document, 1, file.filename or "document", mime_type, data, actor
        )
        await self.audit.record(
            action="documents.uploaded",
            user_id=actor.id,
            entity_type="documents",
            entity_id=document.id,
            new_values={"version_id": str(version.id), "status": document.status},
        )
        await self.notifications.create(
            user_id=actor.id,
            title="Document uploaded",
            body=append_link(
                f"{title} is pending approval.",
                label="Open document",
                url=document_url(document.id, version_id=version.id),
            ),
            notification_type="approval",
            reference_type="document",
            reference_id=document.id,
        )
        document_id = document.id
        await self.session.commit()
        self.session.expire_all()
        return await self._get_required(document_id)

    async def upload_version(self, document_id: UUID, file: UploadFile, actor: User) -> Document:
        document = await self._get_required(document_id)
        await ensure_document_access(self.session, document, actor)
        if document.status == "archived":
            raise AppException("Archived documents cannot be versioned.", status_code=409)
        data = await file.read()
        mime_type = self._validate_file(file.filename or "document", data)
        version_number = await self.documents.next_version(document.id)
        await self._store_version(
            document,
            version_number,
            file.filename or "document",
            mime_type,
            data,
            actor,
        )
        document.status = "pending_approval"
        await self.audit.record(
            action="documents.version_uploaded",
            user_id=actor.id,
            entity_type="documents",
            entity_id=document.id,
            new_values={"version": version_number},
        )
        document_id = document.id
        await self.session.commit()
        self.session.expire_all()
        return await self._get_required(document_id)

    async def approve_version(
        self,
        document_id: UUID,
        version_id: UUID,
        actor: User,
        comments: str | None,
    ) -> Document:
        # Lock the parent row first so two approvers cannot both activate a version and
        # leave the document pointing at a superseded one.
        locked = await self.documents.lock_document(document_id)
        if not locked:
            raise NotFoundException("Document")
        document = await self._get_required(document_id)
        await self._ensure_approver(actor, document)
        version = await self.documents.get_version(version_id)
        if not version or version.document_id != document.id:
            raise NotFoundException("Document version")
        if version.status != "pending_approval":
            raise AppException(
                "Only versions pending approval can be approved.",
                status_code=409,
                error_code="DOCUMENT_VERSION_NOT_PENDING",
            )
        for existing in document.versions:
            if existing.status == "active":
                existing.status = "superseded"
        version.status = "active"
        version.approved_by = actor.id
        version.approved_at = utc_now()
        version.approval_comments = comments
        document.status = "active"
        document.active_version = version.version
        await self.audit.record(
            action="documents.approved",
            user_id=actor.id,
            entity_type="documents",
            entity_id=document.id,
            comments=comments,
            new_values={"active_version": version.version},
        )
        if document.uploaded_by:
            await self.notifications.create(
                user_id=document.uploaded_by,
                title="Document version approved",
                body=append_link(
                    f"{document.title} version {version.version} is now active.",
                    label="Open document",
                    url=document_url(document.id, version_id=version.id),
                ),
                notification_type="approval",
                reference_type="document",
                reference_id=document.id,
            )
        document_id = document.id
        await self.session.commit()
        self.session.expire_all()
        return await self._get_required(document_id)

    async def get(self, document_id: UUID, actor: User) -> Document:
        document = await self._get_required(document_id)
        await ensure_document_access(self.session, document, actor)
        return document

    async def list_document_versions(self, document_id: UUID, actor: User) -> list[DocumentVersion]:
        document = await self.get(document_id, actor)
        return list(document.versions)

    async def list_documents(
        self,
        *,
        project_id: UUID | None,
        document_type: str | None,
        search: str | None,
        actor: User,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Document], int]:
        return await self.documents.list_documents(
            project_id=project_id,
            document_type=document_type,
            search=search,
            limit=limit,
            offset=offset,
            scope_filter=await document_scope_filter(self.session, actor),
        )

    async def signed_download_url(
        self,
        *,
        document_id: UUID,
        version_id: UUID | None,
        actor: User,
    ) -> tuple[str, bool]:
        document = await self._get_required(document_id)
        await ensure_document_access(self.session, document, actor)
        version = self._select_version(document, version_id)
        superseded = version.status == "superseded"
        await self.audit.record(
            action="documents.downloaded",
            user_id=actor.id,
            entity_type="documents",
            entity_id=document.id,
            new_values={"version": version.version, "superseded": superseded},
        )
        await self.session.commit()
        url = minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            version.storage_path,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
        )
        return url, superseded

    async def _store_version(
        self,
        document: Document,
        version_number: int,
        original_name: str,
        mime_type: str,
        data: bytes,
        actor: User,
    ) -> DocumentVersion:
        extension = ".pdf" if mime_type == "application/pdf" else Path(original_name).suffix.lower()
        object_key = f"documents/{document.id}/v{version_number}/{uuid4().hex}{extension}"
        await asyncio.to_thread(self._upload_object, object_key, data, mime_type)
        return await self.documents.add_version(
            DocumentVersion(
                document_id=document.id,
                version=version_number,
                status="pending_approval",
                storage_path=object_key,
                original_name=original_name,
                mime_type=mime_type,
                size_bytes=len(data),
                uploaded_by=actor.id,
            )
        )

    async def _get_required(self, document_id: UUID) -> Document:
        document = await self.documents.get_document(document_id)
        if not document:
            raise NotFoundException("Document")
        return document

    def _select_version(self, document: Document, version_id: UUID | None) -> DocumentVersion:
        if version_id:
            for version in document.versions:
                if version.id == version_id:
                    return version
            raise NotFoundException("Document version")
        for version in document.versions:
            if version.version == document.active_version:
                return version
        raise NotFoundException("Document version")

    async def _ensure_approver(self, actor: User, document: Document) -> None:
        if actor.role not in {ROLE_ADMIN, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER}:
            raise AppException(
                "Document approval is not allowed.",
                status_code=403,
                error_code="DOCUMENT_APPROVAL_FORBIDDEN",
            )
        if document.project_id is None:
            # Company-wide documents have no project membership to check, so they stay
            # with the two roles that already own company-wide configuration.
            if actor.role not in {ROLE_ADMIN, ROLE_OPERATION_MANAGER}:
                raise AppException(
                    "Document approval is not allowed.",
                    status_code=403,
                    error_code="DOCUMENT_APPROVAL_FORBIDDEN",
                )
            return
        if actor.role == ROLE_PROJECT_MANAGER:
            await ensure_project_access(self.session, document.project_id, actor)

    def _validate_file(self, filename: str, data: bytes) -> str:
        if len(data) > MAX_DOCUMENT_SIZE:
            raise AppException("Document exceeds the 60 MB limit.", status_code=413)
        if Path(filename).suffix.lower() in BLOCKED_EXTENSIONS:
            raise AppException("File type is blocked.", status_code=422)
        header = data[:32]
        for mime_type, signatures in ALLOWED_DOCUMENT_MAGIC.items():
            if any(signature in header for signature in signatures):
                return mime_type
        raise AppException("Unsupported document type.", status_code=422)

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
