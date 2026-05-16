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
from app.services.notification_service import NotificationService
from app.utils.exceptions import AppException, NotFoundException
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
            body=f"{title} is pending approval.",
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
        self._ensure_approver(actor)
        document = await self._get_required(document_id)
        version = await self.documents.get_version(version_id)
        if not version or version.document_id != document.id:
            raise NotFoundException("Document version")
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
                body=f"{document.title} version {version.version} is now active.",
                notification_type="approval",
                reference_type="document",
                reference_id=document.id,
            )
        document_id = document.id
        await self.session.commit()
        self.session.expire_all()
        return await self._get_required(document_id)

    async def list_documents(
        self,
        *,
        project_id: UUID | None,
        document_type: str | None,
        search: str | None,
    ) -> tuple[list[Document], int]:
        return await self.documents.list_documents(
            project_id=project_id,
            document_type=document_type,
            search=search,
            limit=100,
            offset=0,
        )

    async def signed_download_url(
        self,
        *,
        document_id: UUID,
        version_id: UUID | None,
        actor: User,
    ) -> tuple[str, bool]:
        document = await self._get_required(document_id)
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
        url = self._client().presigned_get_object(
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
        self._upload_object(object_key, data, mime_type)
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

    def _ensure_approver(self, actor: User) -> None:
        if actor.role not in {ROLE_ADMIN, ROLE_OPERATION_MANAGER, ROLE_PROJECT_MANAGER}:
            raise AppException("Document approval is not allowed.", status_code=403)

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
        return Minio(
            self.settings.minio_endpoint,
            access_key=self.settings.minio_root_user,
            secret_key=self.settings.minio_root_password,
            secure=self.settings.minio_secure,
        )

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
