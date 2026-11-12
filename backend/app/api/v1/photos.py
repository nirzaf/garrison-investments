from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.photos import (
    PhotoDecisionRequest,
    PhotoListResponse,
    PhotoResponse,
    ProtectedFileUrlResponse,
)
from app.services.idempotency import validate_key
from app.services.photo_service import PHOTO_RECOVERY_DAYS, SIGNED_URL_SECONDS, PhotoService
from app.utils.exceptions import AppException
from app.utils.permissions import PERMISSION_REPORTS_SUBMIT, PERMISSION_REPORTS_VIEW

router = APIRouter(prefix="/photos", tags=["Photos"])
CanViewReports = Annotated[User, Depends(require_permission(PERMISSION_REPORTS_VIEW))]
CanSubmitReports = Annotated[User, Depends(require_permission(PERMISSION_REPORTS_SUBMIT))]
MAX_UPLOAD_FILES = 100
MAX_UPLOAD_BATCH_SIZE = 60 * 1024 * 1024


@router.post(
    "/upload",
    response_model=list[PhotoResponse],
    status_code=status.HTTP_201_CREATED,
    responses={201: {"headers": {"X-Report-Revision": {"schema": {"type": "integer"}}}}},
)
async def upload_files(
    current_user: CanSubmitReports,
    session: DbSession,
    response: Response,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[UUID, Form()],
    kind: Annotated[str, Form()] = "photo",
    caption: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    expected_report_revision: Annotated[
        int | None,
        Form(ge=1, description="Required for keyed single-file daily-report uploads."),
    ] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> list[PhotoResponse]:
    if not files:
        raise AppException("Select at least one file.", status_code=422)
    if (
        len(files) > MAX_UPLOAD_FILES
        or sum(file.size or 0 for file in files) > MAX_UPLOAD_BATCH_SIZE
    ):
        raise AppException(
            "An upload may contain up to 100 files and 60 MiB total.",
            status_code=413,
            error_code="UPLOAD_BATCH_TOO_LARGE",
        )
    base_key = validate_key(idempotency_key)
    if (
        entity_type == "daily_report"
        and len(files) == 1
        and base_key
        and expected_report_revision is None
    ):
        raise AppException(
            "Reload the portal and reopen the report before uploading this file.",
            status_code=409,
            error_code="DAILY_REPORT_REVISION_REQUIRED",
        )
    if expected_report_revision is not None and (
        not base_key or len(files) != 1 or entity_type != "daily_report"
    ):
        raise AppException(
            "Versioned uploads require one daily report file and an Idempotency-Key.",
            status_code=422,
            error_code="INVALID_VERSIONED_UPLOAD",
        )
    service = PhotoService(session)
    uploaded = [
        await service.upload(
            file=file,
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            caption=caption,
            actor=current_user,
            # One key per queue item: a multi-file request derives a stable key per file
            # so replaying the batch cannot duplicate any individual upload.
            idempotency_key=f"{base_key}:{index}" if base_key else None,
            expected_report_revision=expected_report_revision,
        )
        for index, file in enumerate(files)
    ]
    if len(uploaded) == 1 and uploaded[0].report_revision is not None:
        response.headers["X-Report-Revision"] = str(uploaded[0].report_revision)
    return [PhotoResponse.model_validate(photo) for photo in uploaded]


@router.get("", response_model=PhotoListResponse)
async def list_files(
    current_user: CanViewReports,
    session: DbSession,
    entity_type: Annotated[str | None, Query()] = None,
    entity_id: Annotated[UUID | None, Query()] = None,
    kind: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    deleted: Annotated[bool, Query()] = False,
) -> PhotoListResponse:
    service = PhotoService(session)
    if deleted:
        photos, total = await service.list_deleted(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            limit=limit,
            offset=offset,
            actor=current_user,
        )
        return PhotoListResponse(
            items=[
                PhotoResponse.model_validate(photo).model_copy(
                    update={
                        "recoverable_until": photo.deleted_at + timedelta(days=PHOTO_RECOVERY_DAYS)
                        if photo.deleted_at
                        else None
                    }
                )
                for photo in photos
            ],
            total=total,
        )
    if entity_type and entity_id:
        photos, total = await service.list_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            actor=current_user,
            limit=limit,
            offset=offset,
        )
    else:
        photos, total = await service.list_recent(
            entity_type=entity_type,
            kind=kind,
            limit=limit,
            offset=offset,
            actor=current_user,
        )
    deletable = await service.deletable_ids(photos, current_user)
    return PhotoListResponse(
        items=[
            PhotoResponse.model_validate(photo).model_copy(
                update={"can_delete": photo.id in deletable}
            )
            for photo in photos
        ],
        total=total,
    )


@router.get("/{photo_id}", response_model=PhotoResponse)
async def get_file(
    photo_id: UUID,
    current_user: CanViewReports,
    session: DbSession,
) -> PhotoResponse:
    photo = await PhotoService(session).get(photo_id, actor=current_user)
    return PhotoResponse.model_validate(photo)


@router.get("/{photo_id}/download", response_model=ProtectedFileUrlResponse)
async def get_file_download_url(
    photo_id: UUID,
    current_user: CanViewReports,
    session: DbSession,
) -> ProtectedFileUrlResponse:
    url = await PhotoService(session).signed_url(photo_id, variant="original", actor=current_user)
    return ProtectedFileUrlResponse(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.get("/{photo_id}/thumbnail", response_model=ProtectedFileUrlResponse)
async def get_thumbnail_url(
    photo_id: UUID,
    current_user: CanViewReports,
    session: DbSession,
) -> ProtectedFileUrlResponse:
    url = await PhotoService(session).signed_url(photo_id, variant="thumbnail", actor=current_user)
    return ProtectedFileUrlResponse(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.delete("/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    photo_id: UUID,
    current_user: CanSubmitReports,
    session: DbSession,
    payload: PhotoDecisionRequest | None = None,
) -> None:
    await PhotoService(session).delete(photo_id, current_user, payload.reason if payload else None)


@router.post("/{photo_id}/recover", response_model=PhotoResponse)
async def recover_file(
    photo_id: UUID,
    current_user: CanViewReports,
    session: DbSession,
    payload: PhotoDecisionRequest | None = None,
) -> PhotoResponse:
    photo = await PhotoService(session).recover(
        photo_id, current_user, payload.reason if payload else None
    )
    return PhotoResponse.model_validate(photo)
