import asyncio
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from fastapi import UploadFile
from minio import Minio
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

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
from app.services.evidence_classification import (
    FINANCIAL,
    OPERATIONAL,
    UNCLASSIFIED,
    EvidenceClassification,
    ensure_evidence_classification_access,
    ensure_evidence_classification_reviewer,
)
from app.services.idempotency import bind, resolve_or_reserve
from app.services.notification_service import NotificationService
from app.services.storage_service import discard_new_uploads, minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.links import append_link, document_url
from app.utils.permissions import (
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_FINANCIAL_VIEW,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now

MAX_DOCUMENT_SIZE = 60 * 1024 * 1024
SIGNED_URL_SECONDS = 300
ALLOWED_DOCUMENT_MAGIC = {
    "application/pdf": (b"%PDF-",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py"}
FINANCIAL_DOCUMENT_TYPES = {"contract", "invoice"}
logger = structlog.get_logger(__name__)


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
        data = await file.read(MAX_DOCUMENT_SIZE + 1)
        mime_type = self._validate_file(file.filename or "document", data)
        if project_id is not None:
            await ensure_project_access(self.session, project_id, actor)
        document = await self.documents.add_document(
            Document(
                title=title,
                document_type=document_type,
                classification=(
                    FINANCIAL
                    if document_type.strip().lower() in FINANCIAL_DOCUMENT_TYPES
                    else UNCLASSIFIED
                ),
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
            new_values={
                "version_id": str(version.id),
                "status": document.status,
                "classification": document.classification,
            },
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

    async def upload_version(
        self, document_id: UUID, file: UploadFile, actor: User, idempotency_key: str | None = None
    ) -> Document:
        document = await self.documents.lock_document(document_id)
        if document is None:
            raise NotFoundException("Document")
        await ensure_document_access(self.session, document, actor)
        self._ensure_evidence_classification_access(document, actor)
        route = f"documents.version:{document_id}"
        if idempotency_key and await resolve_or_reserve(
            self.session, key=idempotency_key, user_id=actor.id, route=route
        ):
            return await self._get_required(document_id)
        if document.status == "archived":
            raise AppException("Archived documents cannot be versioned.", status_code=409)
        data = await file.read(MAX_DOCUMENT_SIZE + 1)
        original_name = file.filename or "document"
        mime_type = self._validate_file(original_name, data)
        version_number = await self.documents.next_version(document.id)
        object_key = self._version_object_key(document_id, version_number, mime_type)
        try:
            version = await self._store_version(
                document, version_number, original_name, mime_type, data, actor, object_key
            )
            if document.active_version is None:
                document.status = "pending_approval"
            await self.audit.record(
                action="documents.version_uploaded",
                user_id=actor.id,
                entity_type="documents",
                entity_id=document.id,
                new_values={"version": version_number},
            )
            if idempotency_key:
                await bind(
                    self.session,
                    key=idempotency_key,
                    user_id=actor.id,
                    route=route,
                    resource_type="document_version",
                    resource_id=version.id,
                )
            await self.session.commit()
        except Exception as error:
            await self._discard_uncommitted_version(object_key)
            logger.warning("document_version_write_failed", error_type=type(error).__name__)
            raise AppException(
                "The replacement version could not be saved. Retry the upload.",
                status_code=503,
                error_code="DOCUMENT_VERSION_SAVE_FAILED",
            ) from error
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
        self._ensure_evidence_classification_access(document, actor)
        if document.status == "archived":
            raise AppException("Archived documents cannot be revised.", status_code=409)
        version = await self.documents.get_version(version_id)
        if not version or version.document_id != document.id:
            raise NotFoundException("Document version")
        if version.uploaded_by == actor.id:
            raise AppException(
                "The person who uploaded a document version cannot approve that version.",
                status_code=403,
                error_code="DOCUMENT_SELF_APPROVAL_FORBIDDEN",
            )
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
        self._ensure_evidence_classification_access(document, actor)
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
            classification_filter=self._classification_filter(actor),
            exclude_document_types=(
                None
                if has_permission(actor, PERMISSION_FINANCIAL_VIEW)
                else FINANCIAL_DOCUMENT_TYPES
            ),
        )

    async def classify_document(
        self,
        document_id: UUID,
        classification: EvidenceClassification,
        reason: str,
        actor: User,
    ) -> Document:
        document = await self.documents.lock_document(document_id)
        if document is None:
            raise NotFoundException("Document")
        await ensure_document_access(self.session, document, actor)
        ensure_evidence_classification_reviewer(actor, document.uploaded_by, classification)
        if document.classification != UNCLASSIFIED:
            raise AppException(
                "Evidence classification has already been reviewed.",
                status_code=409,
                error_code="EVIDENCE_CLASSIFICATION_ALREADY_REVIEWED",
            )
        if (
            document.document_type.strip().lower() in FINANCIAL_DOCUMENT_TYPES
            and classification != FINANCIAL
        ):
            raise AppException(
                "Financial document types must retain the financial classification.",
                status_code=422,
                error_code="EVIDENCE_CLASSIFICATION_INVALID",
            )
        self._ensure_evidence_classification_access(document, actor)
        old_classification = document.classification
        document.classification = classification
        await self.audit.record(
            action="documents.classification_reviewed",
            user_id=actor.id,
            entity_type="documents",
            entity_id=document.id,
            comments=reason,
            old_values={"classification": old_classification},
            new_values={"classification": classification},
        )
        await self.session.commit()
        self.session.expire_all()
        return await self._get_required(document_id)

    async def signed_download_url(
        self,
        *,
        document_id: UUID,
        version_id: UUID | None,
        actor: User,
    ) -> tuple[str, bool]:
        document = await self._get_required(document_id)
        await ensure_document_access(self.session, document, actor)
        self._ensure_evidence_classification_access(document, actor)
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
            response_headers={"response-cache-control": "no-store"},
        )
        return url, superseded

    @staticmethod
    def _ensure_evidence_classification_access(document: Document, actor: User) -> None:
        ensure_evidence_classification_access(
            document.classification,
            document.uploaded_by,
            actor,
            financial_document=document.document_type.strip().lower()
            in FINANCIAL_DOCUMENT_TYPES,
        )

    @staticmethod
    def _classification_filter(actor: User) -> ColumnElement[bool]:
        visible = [Document.classification == OPERATIONAL]
        if has_permission(actor, PERMISSION_DOCUMENTS_MANAGE):
            visible.append(Document.classification == UNCLASSIFIED)
        else:
            visible.append(
                and_(Document.classification == UNCLASSIFIED, Document.uploaded_by == actor.id)
            )
        if has_permission(actor, PERMISSION_FINANCIAL_VIEW):
            visible.append(Document.classification == FINANCIAL)
        return or_(*visible)

    async def _store_version(
        self,
        document: Document,
        version_number: int,
        original_name: str,
        mime_type: str,
        data: bytes,
        actor: User,
        object_key: str | None = None,
    ) -> DocumentVersion:
        object_key = object_key or self._version_object_key(document.id, version_number, mime_type)
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

    def _version_object_key(self, document_id: UUID, version: int, mime_type: str) -> str:
        extension = {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}[
            mime_type
        ]
        return f"documents/{document_id}/v{version}/{uuid4().hex}{extension}"

    async def _discard_uncommitted_version(self, object_key: str) -> None:
        try:
            await self.session.rollback()
            saved = await self.session.scalar(
                select(DocumentVersion.id).where(DocumentVersion.storage_path == object_key)
            )
            if saved is None:
                await discard_new_uploads(self._client(), self.settings.minio_bucket, [object_key])
        except Exception as error:
            logger.warning("document_version_cleanup_unverified", error_type=type(error).__name__)

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
        ensure_permission(actor, PERMISSION_DOCUMENTS_MANAGE)
        if document.project_id is not None:
            await ensure_project_access(self.session, document.project_id, actor)

    def _validate_file(self, filename: str, data: bytes) -> str:
        if len(data) > MAX_DOCUMENT_SIZE:
            raise AppException("Document exceeds the 60 MiB limit.", status_code=413)
        if Path(filename).suffix.lower() in BLOCKED_EXTENSIONS:
            raise AppException("File type is blocked.", status_code=422)
        header = data[:32]
        for mime_type, signatures in ALLOWED_DOCUMENT_MAGIC.items():
            if header.startswith(signatures):
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
