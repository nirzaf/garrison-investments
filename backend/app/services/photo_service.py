import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error
from PIL import Image, ImageDraw
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.config import get_settings
from app.models.daily_report import DailyReport
from app.models.document import Document
from app.models.inventory import InventoryRegistration, MaterialRequest
from app.models.photo import Photo
from app.models.project import Project
from app.models.supervisor_update import SupervisorUpdate, SupervisorUpdateSubmission
from app.models.user import User
from app.repositories.daily_report_repository import DailyReportRepository
from app.repositories.photo_repository import PhotoRepository
from app.repositories.supervisor_update_repository import SupervisorUpdateRepository
from app.services.audit_service import AuditService
from app.services.authorization import (
    accessible_project_ids,
    ensure_entity_access,
    ensure_project_access,
)
from app.services.evidence_classification import (
    FINANCIAL,
    OPERATIONAL,
    UNCLASSIFIED,
    EvidenceClassification,
    effective_document_classification,
    ensure_evidence_classification_access,
    ensure_evidence_classification_reviewer,
    operational_document_predicate,
)
from app.services.idempotency import bind, resolve_or_reserve
from app.services.storage_service import discard_new_uploads, minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    OFFICIAL_REPORT_AUTHOR_ROLES,
    PERMISSION_FINANCIAL_VIEW,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    SUPERVISOR_ROLES,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_REPORT_PHOTOS = 5
UPLOAD_OWNER_TYPES = {
    "daily_report",
    "supervisor_update",
    "inventory_registration",
    "material_request",
}
type PhotoOwner = DailyReport | SupervisorUpdate | InventoryRegistration | MaterialRequest
PHOTO_RECOVERY_DAYS = 30
SIGNED_URL_SECONDS = 300
ALLOWED_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/heic": (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypmif1"),
    "application/pdf": (b"%PDF-",),
}
BLOCKED_EXTENSIONS = {".exe", ".sh", ".bat", ".cmd", ".js", ".ps1", ".php", ".py"}
IDEMPOTENCY_ROUTE = "photos.upload"
logger = structlog.get_logger(__name__)


class PhotoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.settings = get_settings()
        self.photos = PhotoRepository(session)
        self.audit = AuditService(session)

    async def upload(
        self,
        *,
        file: UploadFile,
        entity_type: str,
        entity_id: UUID,
        kind: str,
        caption: str | None,
        actor: User,
        classification: EvidenceClassification = UNCLASSIFIED,
        idempotency_key: str | None = None,
        expected_report_revision: int | None = None,
    ) -> Photo:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        self._validate_entity_type(entity_type)
        normalized_kind = self._validate_kind(kind)
        if classification not in {UNCLASSIFIED, OPERATIONAL, FINANCIAL}:
            raise AppException("Invalid evidence classification.", status_code=422)
        data = await file.read(MAX_FILE_SIZE + 1)
        mime_type = self._validate_file(file.filename or "upload", data, normalized_kind)
        if mime_type == "application/pdf":
            normalized_kind = "attachment"
        if idempotency_key:
            # Reserve before any storage I/O so a replay never re-uploads the bytes.
            existing_id = await resolve_or_reserve(
                self.session,
                key=idempotency_key,
                user_id=actor.id,
                route=IDEMPOTENCY_ROUTE,
            )
            if existing_id is not None:
                existing = await self.photos.get_by_id(existing_id)
                if existing is None:
                    raise NotFoundException("Photo")
                if (
                    (existing.entity_type, existing.entity_id, existing.kind)
                    != (
                        entity_type,
                        entity_id,
                        normalized_kind,
                    )
                    or existing.classification != classification
                    or existing.uploaded_by != actor.id
                ):
                    raise AppException(
                        "This upload key belongs to a different owner, file kind, "
                        "or classification.",
                        status_code=409,
                        error_code="PHOTO_UPLOAD_KEY_CONFLICT",
                    )
                # A retry can arrive after the source draft was submitted. Do not
                # repeat write-time draft/quota checks; revalidate current read
                # scope and let the API return an opaque receipt if needed.
                await ensure_entity_access(
                    self.session, existing.entity_type, existing.entity_id, actor
                )
                if existing.uploaded_by != actor.id:
                    await self._ensure_evidence_classification_access(existing, actor)
                if expected_report_revision is not None and (
                    existing.report_revision != expected_report_revision + 1
                ):
                    self._raise_revision_conflict()
                return existing
        owner = await self._ensure_upload_allowed(entity_type, entity_id, normalized_kind, actor)
        if expected_report_revision is not None and (
            not isinstance(owner, DailyReport) or owner.revision != expected_report_revision
        ):
            self._raise_revision_conflict()
        object_id = uuid4().hex
        extension = self._extension_for_mime(mime_type)
        base_key = f"{entity_type}/{entity_id}/{object_id}"
        storage_path = f"{base_key}/original{extension}"
        compressed_path: str | None = None
        thumbnail_path: str | None = None
        width: int | None = None
        height: int | None = None

        objects = [(storage_path, data, mime_type)]
        if normalized_kind == "photo" and mime_type in {"image/jpeg", "image/png"}:
            try:
                compressed, thumbnail, width, height = await asyncio.to_thread(
                    self._create_photo_variants, data, mime_type
                )
            except (OSError, Image.DecompressionBombError) as error:
                raise AppException(
                    "The image could not be read.", status_code=422, error_code="INVALID_IMAGE"
                ) from error
            compressed_path = f"{base_key}/display.jpg"
            thumbnail_path = f"{base_key}/thumbnail.jpg"
            objects.extend(
                [
                    (compressed_path, compressed, "image/jpeg"),
                    (thumbnail_path, thumbnail, "image/jpeg"),
                ]
            )

        photo = Photo(
            filename=f"{object_id}{extension}",
            original_name=file.filename or "upload",
            storage_path=storage_path,
            compressed_path=compressed_path,
            thumbnail_path=thumbnail_path,
            mime_type=mime_type,
            size_bytes=len(data),
            width=width,
            height=height,
            entity_type=entity_type,
            entity_id=entity_id,
            kind=normalized_kind,
            classification=classification,
            caption=caption,
            uploaded_by=actor.id,
            processing_status="ready",
        )
        written: list[str] = []
        try:
            for object_key, content, content_type in objects:
                written.append(object_key)
                await asyncio.to_thread(self._upload_object, object_key, content, content_type)
            if isinstance(owner, DailyReport):
                owner.revision += 1
                photo.report_revision = owner.revision
            await self.photos.add(photo)
            await self.audit.record(
                action="photos.uploaded",
                user_id=actor.id,
                entity_type=entity_type,
                entity_id=entity_id,
                new_values={
                    "photo_id": str(photo.id),
                    "kind": normalized_kind,
                    "classification": photo.classification,
                },
            )
            if idempotency_key:
                winner_id = await bind(
                    self.session,
                    key=idempotency_key,
                    user_id=actor.id,
                    route=IDEMPOTENCY_ROUTE,
                    resource_type="photo",
                    resource_id=photo.id,
                )
                if winner_id != photo.id:
                    await self._discard_uncommitted_upload(storage_path, written)
                    return await self.get(winner_id, actor=actor)
            await self.session.commit()
        except Exception as error:
            await self._discard_uncommitted_upload(storage_path, written)
            logger.warning("photo_write_failed", error_type=type(error).__name__)
            raise AppException(
                "The file could not be saved. Retry the upload.",
                status_code=503,
                error_code="PHOTO_SAVE_FAILED",
            ) from error
        return photo

    async def _discard_uncommitted_upload(self, storage_path: str, written: list[str]) -> None:
        try:
            await self.session.rollback()
            saved = await self.session.scalar(
                select(Photo.id).where(Photo.storage_path == storage_path)
            )
            if saved is None:
                await discard_new_uploads(self._client(), self.settings.minio_bucket, written)
        except Exception as error:
            logger.warning("photo_cleanup_unverified", error_type=type(error).__name__)

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        kind: str | None,
        actor: User,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Photo], int]:
        self._validate_entity_type(entity_type)
        await ensure_entity_access(self.session, entity_type, entity_id, actor)
        return await self.photos.list_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            limit=limit,
            offset=offset,
            classification_filter=self._classification_filter(
                actor, editable_owner=(entity_type, entity_id)
            ),
        )

    async def list_recent(
        self,
        *,
        entity_type: str | None,
        kind: str | None,
        limit: int,
        offset: int,
        actor: User,
    ) -> tuple[list[Photo], int]:
        if entity_type:
            self._validate_entity_type(entity_type)
            if entity_type != "daily_report":
                # A cross-project feed of project/document/supervisor-update files would
                # leak other teams' evidence; those are only reachable by explicit owner.
                raise AppException(
                    "Recent files must be requested for a specific owner.",
                    status_code=422,
                    error_code="ENTITY_ID_REQUIRED",
                )
        if kind:
            normalized_kind = kind.strip().lower()
            if normalized_kind not in {"photo", "attachment"}:
                raise AppException(
                    "Invalid file kind.",
                    status_code=422,
                    error_code="INVALID_FILE_KIND",
                )
            kind = normalized_kind
        if not has_permission(actor, PERMISSION_REPORTS_VIEW):
            return [], 0
        return await self.photos.list_recent(
            entity_type=entity_type,
            kind=kind,
            limit=limit,
            offset=offset,
            project_ids=await accessible_project_ids(self.session, actor),
            engineer_id=None,
            classification_filter=self._classification_filter(actor),
        )

    async def get(self, photo_id: UUID, *, actor: User) -> Photo:
        candidate = await self.photos.get_by_id(photo_id)
        if candidate is None:
            raise NotFoundException("Photo")
        if candidate.entity_type == "document":
            parent = await self.session.scalar(
                select(Document)
                .where(Document.id == candidate.entity_id, Document.deleted_at.is_(None))
                .options(selectinload(Document.versions))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if parent is None:
                raise NotFoundException("Photo")
        photo = await self.photos.get_by_id(photo_id, for_update=True)
        if photo is None:
            raise NotFoundException("Photo")
        await ensure_entity_access(self.session, photo.entity_type, photo.entity_id, actor)
        await self._ensure_evidence_classification_access(photo, actor)
        return photo

    async def classify(
        self,
        photo_id: UUID,
        classification: EvidenceClassification,
        reason: str,
        actor: User,
        expected_classification: EvidenceClassification,
        expected_updated_at: datetime,
    ) -> Photo:
        candidate = await self.photos.get_by_id(photo_id)
        if candidate is None:
            raise NotFoundException("Photo")
        parent: Document | None = None
        if candidate.entity_type == "document":
            parent = await self.session.scalar(
                select(Document)
                .where(Document.id == candidate.entity_id, Document.deleted_at.is_(None))
                .options(selectinload(Document.versions))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if parent is None:
                raise NotFoundException("Photo")
        photo = await self.photos.get_by_id(photo_id, for_update=True)
        if photo is None:
            raise NotFoundException("Photo")
        await ensure_entity_access(self.session, photo.entity_type, photo.entity_id, actor)
        ensure_evidence_classification_reviewer(actor, photo.uploaded_by, classification)
        if parent is not None and (
            effective_document_classification(parent) == FINANCIAL
            or parent.document_type.strip().lower() in {"contract", "invoice"}
        ) and classification != FINANCIAL:
            raise AppException(
                "Media attached to financial documents must remain restricted.",
                status_code=422,
                error_code="EVIDENCE_CLASSIFICATION_INVALID",
            )
        if (
            photo.classification != expected_classification
            or photo.updated_at != expected_updated_at
        ):
            raise AppException(
                "Evidence classification changed. Reload it before reviewing.",
                status_code=409,
                error_code="EVIDENCE_CLASSIFICATION_CONFLICT",
            )
        if photo.classification == FINANCIAL and classification != FINANCIAL:
            raise AppException(
                "Financial evidence cannot be reclassified as operational.",
                status_code=422,
                error_code="EVIDENCE_CLASSIFICATION_INVALID",
            )
        if photo.classification == classification:
            raise AppException(
                "Choose a stricter or unresolved classification for this review.",
                status_code=409,
                error_code="EVIDENCE_CLASSIFICATION_ALREADY_REVIEWED",
            )
        old_classification = photo.classification
        photo.classification = classification
        await self.audit.record(
            action="photos.classification_reviewed",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            comments=reason,
            old_values={"photo_id": str(photo.id), "classification": old_classification},
            new_values={"photo_id": str(photo.id), "classification": classification},
        )
        await self.session.commit()
        self.session.expire_all()
        reviewed_photo = await self.photos.get_by_id(photo_id)
        if reviewed_photo is None:
            raise NotFoundException("Photo")
        return reviewed_photo

    async def signed_url(self, photo_id: UUID, *, variant: str, actor: User) -> str:
        photo = await self.get(photo_id, actor=actor)
        object_key = self._object_key_for_variant(photo, variant)
        await self.audit.record(
            action=f"photos.{variant}.downloaded",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            new_values={"photo_id": str(photo.id)},
        )
        await self.session.commit()
        return minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            object_key,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
            response_headers={"response-cache-control": "no-store"},
        )

    async def _ensure_evidence_classification_access(self, photo: Photo, actor: User) -> None:
        ensure_evidence_classification_access(photo.classification, photo.uploaded_by, actor)
        if photo.entity_type == "document":
            document = await self.session.scalar(
                select(Document)
                .where(Document.id == photo.entity_id, Document.deleted_at.is_(None))
                .options(selectinload(Document.versions))
            )
            if document is None:
                raise NotFoundException("Evidence")
            ensure_evidence_classification_access(
                effective_document_classification(document),
                document.uploaded_by,
                actor,
                financial_document=document.document_type.strip().lower()
                in {"contract", "invoice"},
            )

    @staticmethod
    def _classification_filter(
        actor: User, editable_owner: tuple[str, UUID] | None = None
    ) -> ColumnElement[bool]:
        if has_permission(actor, PERMISSION_FINANCIAL_VIEW):
            return Photo.classification.in_({UNCLASSIFIED, OPERATIONAL, FINANCIAL})
        operational_document = (
            select(Document.id)
            .where(
                Document.id == Photo.entity_id,
                Document.deleted_at.is_(None),
            operational_document_predicate(),
            )
            .exists()
        )
        operational = and_(
            Photo.classification == OPERATIONAL,
            or_(Photo.entity_type != "document", operational_document),
        )
        if editable_owner is None:
            return operational
        entity_type, entity_id = editable_owner
        owner: ColumnElement[bool]
        if entity_type == "daily_report":
            owner = (
                select(DailyReport.id)
                .where(
                    DailyReport.id == entity_id,
                    DailyReport.engineer_id == actor.id,
                    DailyReport.status == "draft",
                    DailyReport.deleted_at.is_(None),
                )
                .exists()
            )
        elif entity_type == "supervisor_update":
            owner = (
                select(SupervisorUpdate.id)
                .where(
                    SupervisorUpdate.id == entity_id,
                    SupervisorUpdate.supervisor_id == actor.id,
                    SupervisorUpdate.status == "draft",
                    SupervisorUpdate.deleted_at.is_(None),
                )
                .exists()
            )
        elif entity_type == "material_request":
            owner = (
                select(MaterialRequest.id)
                .where(
                    MaterialRequest.id == entity_id,
                    MaterialRequest.requester_id == actor.id,
                    MaterialRequest.status == "draft",
                    MaterialRequest.deleted_at.is_(None),
                )
                .exists()
            )
        elif entity_type == "inventory_registration":
            owner = (
                select(InventoryRegistration.id)
                .where(
                    InventoryRegistration.id == entity_id,
                    InventoryRegistration.created_by == actor.id,
                    InventoryRegistration.status == "draft",
                )
                .exists()
            )
        else:
            return operational
        restricted_receipt = and_(
            Photo.entity_type == entity_type,
            Photo.entity_id == entity_id,
            Photo.classification.in_({UNCLASSIFIED, FINANCIAL}),
            owner,
        )
        return or_(operational, restricted_receipt)

    async def deletable_ids(self, photos: list[Photo], actor: User) -> set[UUID]:
        if not has_permission(actor, PERMISSION_REPORTS_SUBMIT):
            return set()
        project_ids = await accessible_project_ids(self.session, actor)
        editable_by_type: dict[str, set[UUID]] = {}
        if actor.role in OFFICIAL_REPORT_AUTHOR_ROLES:
            report_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "daily_report"
            ]
            if report_ids:
                project_filter = (
                    DailyReport.project_id.is_not(None)
                    if project_ids is None
                    else DailyReport.project_id.in_(project_ids or [])
                )
                owners = await self.session.scalars(
                    select(DailyReport.id).where(
                        DailyReport.id.in_(report_ids),
                        DailyReport.engineer_id == actor.id,
                        project_filter,
                        DailyReport.status == "draft",
                        DailyReport.deleted_at.is_(None),
                    )
                )
                editable_by_type["daily_report"] = set(owners)
        if actor.role in SUPERVISOR_ROLES:
            update_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "supervisor_update"
            ]
            if update_ids:
                owners = await self.session.scalars(
                    select(SupervisorUpdate.id).where(
                        SupervisorUpdate.id.in_(update_ids),
                        SupervisorUpdate.supervisor_id == actor.id,
                        (
                            SupervisorUpdate.project_id.is_not(None)
                            if project_ids is None
                            else SupervisorUpdate.project_id.in_(project_ids or [])
                        ),
                        SupervisorUpdate.status == "draft",
                        SupervisorUpdate.deleted_at.is_(None),
                    )
                )
                editable_by_type["supervisor_update"] = set(owners)
            material_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "material_request"
            ]
            if material_ids:
                active_projects = select(Project.id).where(
                    Project.status == "active", Project.deleted_at.is_(None)
                )
                owners = await self.session.scalars(
                    select(MaterialRequest.id).where(
                        MaterialRequest.id.in_(material_ids),
                        MaterialRequest.requester_id == actor.id,
                        MaterialRequest.status == "draft",
                        MaterialRequest.deleted_at.is_(None),
                        MaterialRequest.project_id.in_(active_projects),
                        (
                            MaterialRequest.project_id.is_not(None)
                            if project_ids is None
                            else MaterialRequest.project_id.in_(project_ids or [])
                        ),
                    )
                )
                editable_by_type["material_request"] = set(owners)
            registration_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "inventory_registration"
            ]
            if registration_ids:
                owners = await self.session.scalars(
                    select(InventoryRegistration.id).where(
                        InventoryRegistration.id.in_(registration_ids),
                        InventoryRegistration.created_by == actor.id,
                        InventoryRegistration.status == "draft",
                        (
                            InventoryRegistration.project_id.is_not(None)
                            if project_ids is None
                            else InventoryRegistration.project_id.in_(project_ids or [])
                        ),
                    )
                )
                editable_by_type["inventory_registration"] = set(owners)
        return {
            photo.id
            for photo in photos
            if photo.entity_id in editable_by_type.get(photo.entity_type, set())
        }

    async def list_deleted(
        self,
        *,
        entity_type: str | None,
        entity_id: UUID | None,
        kind: str | None,
        limit: int,
        offset: int,
        actor: User,
    ) -> tuple[list[Photo], int]:
        self._ensure_recovery_disabled()
        if entity_type:
            self._validate_entity_type(entity_type)
        if kind and kind not in {"photo", "attachment"}:
            raise AppException(
                "Invalid file kind.", status_code=422, error_code="INVALID_FILE_KIND"
            )
        return await self.photos.list_deleted(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            limit=limit,
            offset=offset,
            classification_filter=self._classification_filter(actor),
        )

    async def delete(self, photo_id: UUID, actor: User, reason: str | None = None) -> None:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        existing = await self.photos.get_by_id(photo_id)
        if existing is None:
            raise NotFoundException("Photo")
        if (
            existing.classification in {UNCLASSIFIED, FINANCIAL}
            and not has_permission(actor, PERMISSION_FINANCIAL_VIEW)
            and existing.uploaded_by != actor.id
        ):
            raise NotFoundException("Photo")
        owner = await self._lock_owner(existing.entity_type, existing.entity_id, actor)
        photo = await self.photos.get_by_id(photo_id, for_update=True)
        if photo is None:
            raise NotFoundException("Photo")
        await self._ensure_author(owner, actor)
        if owner is None or owner.status != "draft":
            raise AppException(
                "Files can only be removed from editable drafts.",
                status_code=409,
                error_code="PHOTO_DELETE_LOCKED",
            )
        if isinstance(owner, SupervisorUpdate) and await self.session.scalar(
            select(SupervisorUpdateSubmission.update_id)
            .where(
                SupervisorUpdateSubmission.update_id == owner.id,
                SupervisorUpdateSubmission.evidence_ids.contains([str(photo.id)]),
            )
            .limit(1)
        ):
            raise AppException(
                "Submitted photo evidence must be retained.",
                status_code=409,
                error_code="PHOTO_RETAINED_EVIDENCE",
            )
        reason = self._evidence_reason(owner, actor, reason)
        photo.deleted_at = utc_now()
        if isinstance(owner, DailyReport):
            owner.revision += 1
        await self.audit.record(
            action="photos.deleted",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            comments=reason,
            new_values={"photo_id": str(photo.id)},
        )
        await self.session.commit()

    async def recover(self, photo_id: UUID, actor: User, reason: str | None = None) -> Photo:
        self._ensure_recovery_disabled()
        photo = await self.photos.get_deleted_by_id(photo_id)
        if photo is None:
            raise NotFoundException("Photo")
        await self._ensure_evidence_classification_access(photo, actor)
        owner = await self._lock_owner(photo.entity_type, photo.entity_id, actor)
        photo = await self.photos.get_deleted_by_id(photo_id, for_update=True)
        if photo is None:
            raise NotFoundException("Photo")
        await self._ensure_evidence_classification_access(photo, actor)
        recovery_cutoff = utc_now() - timedelta(days=PHOTO_RECOVERY_DAYS)
        if photo.deleted_at and photo.deleted_at < recovery_cutoff:
            raise AppException(
                "Photo recovery window has expired.",
                status_code=409,
                error_code="PHOTO_RECOVERY_EXPIRED",
            )
        await self._ensure_photo_capacity(photo.entity_type, photo.entity_id, photo.kind)
        reason = self._evidence_reason(owner, actor, reason)
        client = self._client()
        for path in (photo.storage_path, photo.compressed_path, photo.thumbnail_path):
            if path:
                try:
                    await asyncio.to_thread(client.stat_object, self.settings.minio_bucket, path)
                except S3Error as error:
                    if error.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                        raise AppException(
                            "One or more stored files are unavailable for recovery.",
                            status_code=409,
                            error_code="PHOTO_RECOVERY_UNAVAILABLE",
                        ) from error
                    raise
        photo.deleted_at = None
        if isinstance(owner, DailyReport):
            owner.revision += 1
        await self.audit.record(
            action="photos.recovered",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            comments=reason,
            new_values={"photo_id": str(photo.id)},
        )
        await self.session.commit()
        return photo

    def _evidence_reason(
        self, owner: PhotoOwner | None, actor: User, reason: str | None
    ) -> str | None:
        reason = reason.strip() if reason else None
        return reason

    @staticmethod
    def _ensure_recovery_disabled() -> None:
        raise AppException(
            "Deleted-media recovery is unavailable because no role has that privilege.",
            status_code=403,
            error_code="PHOTO_RECOVERY_FORBIDDEN",
        )

    async def _lock_owner(
        self, entity_type: str, entity_id: UUID, actor: User
    ) -> PhotoOwner | None:
        owner: PhotoOwner | None = None
        if entity_type == "daily_report":
            owner = await DailyReportRepository(self.session).lock_by_id(entity_id)
            if owner is None:
                raise NotFoundException("Daily report")
        elif entity_type == "supervisor_update":
            owner = await SupervisorUpdateRepository(self.session).get_by_id(
                entity_id, for_update=True
            )
            if owner is None:
                raise NotFoundException("Supervisor update")
        elif entity_type == "material_request":
            owner = await self.session.scalar(
                select(MaterialRequest)
                .where(MaterialRequest.id == entity_id, MaterialRequest.deleted_at.is_(None))
                .with_for_update()
            )
            if owner is None:
                raise NotFoundException("Material request")
        elif entity_type == "inventory_registration":
            owner = await self.session.scalar(
                select(InventoryRegistration)
                .where(InventoryRegistration.id == entity_id)
                .with_for_update()
            )
            if owner is None:
                raise NotFoundException("Inventory registration")
        elif entity_type == "project":
            project = await self.session.scalar(
                select(Project.id)
                .where(Project.id == entity_id, Project.deleted_at.is_(None))
                .with_for_update()
            )
            if project is None:
                raise NotFoundException("Project")
        await ensure_entity_access(self.session, entity_type, entity_id, actor)
        return owner

    async def _ensure_author(self, owner: PhotoOwner | None, actor: User) -> None:
        if isinstance(owner, DailyReport):
            owns_draft = (
                actor.role in OFFICIAL_REPORT_AUTHOR_ROLES
                and has_permission(actor, PERMISSION_REPORTS_SUBMIT)
                and owner.engineer_id == actor.id
            )
        elif isinstance(owner, SupervisorUpdate):
            owns_draft = (
                actor.role in SUPERVISOR_ROLES
                and has_permission(actor, PERMISSION_REPORTS_SUBMIT)
                and owner.supervisor_id == actor.id
            )
        elif isinstance(owner, MaterialRequest):
            owns_draft = actor.role in SUPERVISOR_ROLES and owner.requester_id == actor.id
            if owns_draft and not await self.session.scalar(
                select(Project.id).where(
                    Project.id == owner.project_id,
                    Project.status == "active",
                    Project.deleted_at.is_(None),
                )
            ):
                raise NotFoundException("Active project")
        elif isinstance(owner, InventoryRegistration):
            owns_draft = actor.role in SUPERVISOR_ROLES and owner.created_by == actor.id
        else:
            owns_draft = False
        if not owns_draft or owner is None:
            raise NotFoundException("Photo")
        await ensure_project_access(self.session, owner.project_id, actor)

    async def _ensure_upload_allowed(
        self,
        entity_type: str,
        entity_id: UUID,
        kind: str,
        actor: User,
    ) -> PhotoOwner | None:
        owner = await self._lock_owner(entity_type, entity_id, actor)
        if entity_type not in UPLOAD_OWNER_TYPES:
            raise AppException(
                "This file owner type does not accept evidence uploads.",
                status_code=403,
                error_code="PHOTO_OWNER_FORBIDDEN",
            )
        if owner is not None:
            await self._ensure_author(owner, actor)
            if owner.status != "draft":
                raise AppException(
                    "Files can only be added to editable drafts.",
                    status_code=409,
                    error_code="PHOTO_UPLOAD_LOCKED",
                )
        await self._ensure_photo_capacity(entity_type, entity_id, kind)
        return owner

    @staticmethod
    def _raise_revision_conflict() -> None:
        raise AppException(
            "The report changed. Reload before adding evidence.",
            status_code=409,
            error_code="DAILY_REPORT_REVISION_CONFLICT",
        )

    async def _ensure_photo_capacity(self, entity_type: str, entity_id: UUID, kind: str) -> None:
        if kind != "photo" or entity_type not in UPLOAD_OWNER_TYPES:
            return
        if await self.photos.count_photos(entity_type, entity_id) >= MAX_REPORT_PHOTOS:
            owner_label = {
                "daily_report": "report",
                "supervisor_update": "site update",
                "inventory_registration": "registration",
                "material_request": "material request",
            }[entity_type]
            raise AppException(
                f"This {owner_label} already has {MAX_REPORT_PHOTOS} active photos.",
                status_code=409,
                error_code="REPORT_PHOTO_LIMIT_REACHED",
            )

    def _validate_entity_type(self, entity_type: str) -> None:
        if entity_type not in UPLOAD_OWNER_TYPES | {"project", "document"}:
            raise AppException(
                "Invalid file owner.",
                status_code=422,
                error_code="INVALID_ENTITY_TYPE",
            )

    def _validate_kind(self, kind: str) -> str:
        normalized = kind.strip().lower()
        if normalized not in {"photo", "attachment"}:
            raise AppException(
                "Invalid file kind.",
                status_code=422,
                error_code="INVALID_FILE_KIND",
            )
        return normalized

    def _validate_file(self, filename: str, data: bytes, kind: str) -> str:
        if len(data) > MAX_FILE_SIZE:
            raise AppException(
                "File exceeds the 10 MiB limit.",
                status_code=413,
                error_code="FILE_TOO_LARGE",
            )
        if Path(filename).suffix.lower() in BLOCKED_EXTENSIONS:
            raise AppException(
                "File type is blocked.",
                status_code=422,
                error_code="BLOCKED_FILE_TYPE",
            )
        mime_type = self._detect_mime(data)
        if kind == "photo" and mime_type not in {
            "image/jpeg",
            "image/png",
            "image/heic",
            "application/pdf",
        }:
            raise AppException(
                "Unsupported photo type.",
                status_code=422,
                error_code="UNSUPPORTED_PHOTO_TYPE",
            )
        if kind == "attachment" and mime_type not in {"application/pdf", "image/jpeg", "image/png"}:
            raise AppException(
                "Unsupported attachment type.",
                status_code=422,
                error_code="UNSUPPORTED_ATTACHMENT_TYPE",
            )
        return mime_type

    def _detect_mime(self, data: bytes) -> str:
        header = data[:32]
        for mime_type, signatures in ALLOWED_MAGIC.items():
            prefix = header[4:] if mime_type == "image/heic" else header
            if prefix.startswith(signatures):
                return mime_type
        raise AppException(
            "Unsupported file type.",
            status_code=422,
            error_code="UNSUPPORTED_FILE_TYPE",
        )

    def _extension_for_mime(self, mime_type: str) -> str:
        return {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/heic": ".heic",
            "application/pdf": ".pdf",
        }[mime_type]

    def _create_photo_variants(self, data: bytes, mime_type: str) -> tuple[bytes, bytes, int, int]:
        with Image.open(BytesIO(data)) as source:
            image = source.convert("RGB")
            width, height = image.size
            display = image.copy()
            display.thumbnail((1600, 1600))
            draw = ImageDraw.Draw(display)
            draw.text(
                (12, max(display.height - 28, 12)),
                "Garrisons Investments",
                fill=(255, 255, 255),
            )
            display_buffer = BytesIO()
            display.save(display_buffer, format="JPEG", quality=82)
            thumbnail = image.copy()
            thumbnail.thumbnail((360, 360))
            thumb_buffer = BytesIO()
            thumbnail.save(thumb_buffer, format="JPEG", quality=75)
            return display_buffer.getvalue(), thumb_buffer.getvalue(), width, height

    def _object_key_for_variant(self, photo: Photo, variant: str) -> str:
        if variant == "thumbnail":
            return photo.thumbnail_path or photo.storage_path
        if variant == "display":
            return photo.compressed_path or photo.storage_path
        return photo.storage_path

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
