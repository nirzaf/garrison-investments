import asyncio
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

import structlog
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error
from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.daily_report import DailyReport
from app.models.photo import Photo
from app.models.project import Project
from app.models.supervisor_update import SupervisorUpdate
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
from app.services.idempotency import bind, resolve_or_reserve
from app.services.storage_service import discard_new_uploads, minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import (
    OFFICIAL_REPORT_AUTHOR_ROLES,
    PERMISSION_REPORTS_SUBMIT,
    PERMISSION_REPORTS_VIEW,
    SUPERVISOR_ROLES,
    ensure_permission,
    has_permission,
)
from app.utils.security import utc_now

MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_REPORT_PHOTOS = 5
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
        idempotency_key: str | None = None,
        expected_report_revision: int | None = None,
    ) -> Photo:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        self._validate_entity_type(entity_type)
        normalized_kind = self._validate_kind(kind)
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
                # A replay is still subject to current access to the original photo.
                existing = await self.get(existing_id, actor=actor)
                if (existing.entity_type, existing.entity_id, existing.kind) != (
                    entity_type,
                    entity_id,
                    normalized_kind,
                ):
                    raise AppException(
                        "This upload key belongs to a different file operation.",
                        status_code=409,
                        error_code="PHOTO_UPLOAD_KEY_CONFLICT",
                    )
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
                new_values={"photo_id": str(photo.id), "kind": normalized_kind},
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
        )

    async def get(self, photo_id: UUID, *, actor: User) -> Photo:
        photo = await self.photos.get_by_id(photo_id)
        if not photo:
            raise NotFoundException("Photo")
        await ensure_entity_access(self.session, photo.entity_type, photo.entity_id, actor)
        return photo

    async def signed_url(self, photo_id: UUID, *, variant: str, actor: User) -> str:
        photo = await self.get(photo_id, actor=actor)
        object_key = self._object_key_for_variant(photo, variant)
        await self.audit.record(
            action=f"photos.{variant}.downloaded",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            new_values={"photo_id": str(photo.id), "object_key": object_key},
        )
        await self.session.commit()
        return minio_signed_url_client(self.settings).presigned_get_object(
            self.settings.minio_bucket,
            object_key,
            expires=timedelta(seconds=SIGNED_URL_SECONDS),
        )

    async def deletable_ids(self, photos: list[Photo], actor: User) -> set[UUID]:
        if not has_permission(actor, PERMISSION_REPORTS_SUBMIT):
            return set()
        project_ids = await accessible_project_ids(self.session, actor)
        project_filter = (
            DailyReport.project_id.is_not(None)
            if project_ids is None
            else DailyReport.project_id.in_(project_ids or [])
        )
        if actor.role in OFFICIAL_REPORT_AUTHOR_ROLES:
            report_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "daily_report"
            ]
            if not report_ids:
                return set()
            owners = await self.session.scalars(
                select(DailyReport.id).where(
                    DailyReport.id.in_(report_ids),
                    DailyReport.engineer_id == actor.id,
                    project_filter,
                    DailyReport.status == "draft",
                    DailyReport.deleted_at.is_(None),
                )
            )
            entity_type = "daily_report"
        elif actor.role in SUPERVISOR_ROLES:
            update_ids = [
                photo.entity_id for photo in photos if photo.entity_type == "supervisor_update"
            ]
            if not update_ids:
                return set()
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
            entity_type = "supervisor_update"
        else:
            return set()
        editable = set(owners)
        return {
            photo.id
            for photo in photos
            if photo.entity_type == entity_type and photo.entity_id in editable
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
            entity_type=entity_type, entity_id=entity_id, kind=kind, limit=limit, offset=offset
        )

    async def delete(self, photo_id: UUID, actor: User, reason: str | None = None) -> None:
        ensure_permission(actor, PERMISSION_REPORTS_SUBMIT)
        existing = await self.get(photo_id, actor=actor)
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
        owner = await self._lock_owner(photo.entity_type, photo.entity_id, actor)
        photo = await self.photos.get_deleted_by_id(photo_id, for_update=True)
        if photo is None:
            raise NotFoundException("Photo")
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
        self, owner: DailyReport | SupervisorUpdate | None, actor: User, reason: str | None
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
    ) -> DailyReport | SupervisorUpdate | None:
        owner: DailyReport | SupervisorUpdate | None = None
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

    async def _ensure_author(
        self, owner: DailyReport | SupervisorUpdate | None, actor: User
    ) -> None:
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
    ) -> DailyReport | SupervisorUpdate | None:
        owner = await self._lock_owner(entity_type, entity_id, actor)
        if entity_type not in {"daily_report", "supervisor_update"}:
            raise AppException(
                "This file owner type is not available through report uploads.",
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
        if kind != "photo" or entity_type not in {"daily_report", "supervisor_update"}:
            return
        if await self.photos.count_photos(entity_type, entity_id) >= MAX_REPORT_PHOTOS:
            owner_label = "report" if entity_type == "daily_report" else "site update"
            raise AppException(
                f"This {owner_label} already has {MAX_REPORT_PHOTOS} active photos.",
                status_code=409,
                error_code="REPORT_PHOTO_LIMIT_REACHED",
            )

    def _validate_entity_type(self, entity_type: str) -> None:
        if entity_type not in {"daily_report", "project", "supervisor_update", "document"}:
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
