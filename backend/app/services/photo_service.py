import asyncio
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from minio import Minio
from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.photo import Photo
from app.models.user import User
from app.repositories.photo_repository import PhotoRepository
from app.services.audit_service import AuditService
from app.services.authorization import accessible_project_ids, ensure_entity_access
from app.services.idempotency import bind, resolve_or_reserve
from app.services.report_service import ReportService
from app.services.storage_service import minio_client, minio_signed_url_client
from app.utils.exceptions import AppException, NotFoundException
from app.utils.permissions import ROLE_ADMIN
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
    ) -> Photo:
        self._validate_entity_type(entity_type)
        normalized_kind = self._validate_kind(kind, file.filename or "")
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
                return await self.get(existing_id, actor=actor)
        await self._ensure_upload_allowed(entity_type, entity_id, normalized_kind, actor)
        data = await file.read()
        mime_type = self._validate_file(file.filename or "upload", data, normalized_kind)
        object_id = uuid4().hex
        extension = self._extension_for_mime(mime_type)
        base_key = f"{entity_type}/{entity_id}/{object_id}"
        storage_path = f"{base_key}/original{extension}"
        compressed_path: str | None = None
        thumbnail_path: str | None = None
        width: int | None = None
        height: int | None = None

        await asyncio.to_thread(self._upload_object, storage_path, data, mime_type)
        if normalized_kind == "photo" and mime_type in {"image/jpeg", "image/png"}:
            compressed, thumbnail, width, height = await asyncio.to_thread(
                self._create_photo_variants, data, mime_type
            )
            compressed_path = f"{base_key}/display.jpg"
            thumbnail_path = f"{base_key}/thumbnail.jpg"
            await asyncio.to_thread(self._upload_object, compressed_path, compressed, "image/jpeg")
            await asyncio.to_thread(self._upload_object, thumbnail_path, thumbnail, "image/jpeg")

        photo = await self.photos.add(
            Photo(
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
        )
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
                await self.session.rollback()
                winner = await self.photos.get_by_id(winner_id)
                if winner is not None:
                    return winner
        await self.session.commit()
        return photo

    async def list_for_entity(
        self,
        *,
        entity_type: str,
        entity_id: UUID,
        kind: str | None,
        actor: User,
    ) -> tuple[list[Photo], int]:
        self._validate_entity_type(entity_type)
        await ensure_entity_access(self.session, entity_type, entity_id, actor)
        return await self.photos.list_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
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
        return await self.photos.list_recent(
            entity_type=entity_type,
            kind=kind,
            limit=limit,
            offset=offset,
            project_ids=await accessible_project_ids(self.session, actor),
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

    async def delete(self, photo_id: UUID, actor: User) -> None:
        photo = await self.get(photo_id, actor=actor)
        if photo.entity_type == "daily_report":
            report = await ReportService(self.session).get_report_for_export(photo.entity_id)
            if report.status != "draft" and actor.role != ROLE_ADMIN:
                raise AppException(
                    "Photos cannot be deleted after report submission.",
                    status_code=409,
                    error_code="PHOTO_DELETE_LOCKED",
                )
        photo.deleted_at = utc_now()
        await self.audit.record(
            action="photos.deleted",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            new_values={"photo_id": str(photo.id)},
        )
        await self.session.commit()

    async def recover(self, photo_id: UUID, actor: User) -> Photo:
        if actor.role != ROLE_ADMIN:
            raise AppException(
                "Only Admin can recover deleted photos.",
                status_code=403,
                error_code="PHOTO_RECOVERY_FORBIDDEN",
            )
        photo = await self.photos.get_deleted_by_id(photo_id)
        if not photo:
            raise NotFoundException("Photo")
        recovery_cutoff = utc_now() - timedelta(days=PHOTO_RECOVERY_DAYS)
        if photo.deleted_at and photo.deleted_at < recovery_cutoff:
            raise AppException(
                "Photo recovery window has expired.",
                status_code=409,
                error_code="PHOTO_RECOVERY_EXPIRED",
            )
        photo.deleted_at = None
        await self.audit.record(
            action="photos.recovered",
            user_id=actor.id,
            entity_type=photo.entity_type,
            entity_id=photo.entity_id,
            new_values={"photo_id": str(photo.id)},
        )
        await self.session.commit()
        return photo

    async def _ensure_upload_allowed(
        self,
        entity_type: str,
        entity_id: UUID,
        kind: str,
        actor: User,
    ) -> None:
        if entity_type == "daily_report":
            report = await ReportService(self.session).get_report(entity_id, actor)
            if report.status != "draft":
                raise AppException(
                    "Files can only be added to draft reports.",
                    status_code=409,
                    error_code="PHOTO_UPLOAD_LOCKED",
                )
            if kind == "photo":
                _, total = await self.photos.list_for_entity(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    kind="photo",
                )
                if total >= MAX_REPORT_PHOTOS:
                    raise AppException(
                        "A report can have a maximum of 5 photos.",
                        status_code=409,
                        error_code="REPORT_PHOTO_LIMIT_REACHED",
                    )
        else:
            # get_report above already scopes daily reports; every other owner needs the
            # same check before bytes are written to storage.
            await ensure_entity_access(self.session, entity_type, entity_id, actor)

    def _validate_entity_type(self, entity_type: str) -> None:
        if entity_type not in {"daily_report", "project", "supervisor_update", "document"}:
            raise AppException(
                "Invalid file owner.",
                status_code=422,
                error_code="INVALID_ENTITY_TYPE",
            )

    def _validate_kind(self, kind: str, filename: str) -> str:
        normalized = kind.strip().lower()
        if normalized not in {"photo", "attachment"}:
            raise AppException(
                "Invalid file kind.",
                status_code=422,
                error_code="INVALID_FILE_KIND",
            )
        if Path(filename).suffix.lower() == ".pdf":
            return "attachment"
        return normalized

    def _validate_file(self, filename: str, data: bytes, kind: str) -> str:
        if len(data) > MAX_FILE_SIZE:
            raise AppException(
                "File exceeds the 10 MB limit.",
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
        if kind == "photo" and mime_type not in {"image/jpeg", "image/png", "image/heic"}:
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
            if any(signature in header for signature in signatures):
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
