from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile, status

from app.api.dependencies import DbSession, require_permission
from app.models.user import User
from app.schemas.photos import PhotoListResponse, PhotoResponse, ProtectedFileUrlResponse
from app.services.idempotency import validate_key
from app.services.photo_service import SIGNED_URL_SECONDS, PhotoService
from app.utils.permissions import PERMISSION_REPORTS_SUBMIT, PERMISSION_REPORTS_VIEW, ROLE_ADMIN

router = APIRouter(prefix="/photos", tags=["Photos"])
CanViewReports = Annotated[User, Depends(require_permission(PERMISSION_REPORTS_VIEW))]
CanSubmitReports = Annotated[User, Depends(require_permission(PERMISSION_REPORTS_SUBMIT))]


@router.post("/upload", response_model=list[PhotoResponse], status_code=status.HTTP_201_CREATED)
async def upload_files(
    current_user: CanSubmitReports,
    session: DbSession,
    entity_type: Annotated[str, Form()],
    entity_id: Annotated[UUID, Form()],
    kind: Annotated[str, Form()] = "photo",
    caption: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> list[PhotoResponse]:
    service = PhotoService(session)
    base_key = validate_key(idempotency_key)
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
        )
        for index, file in enumerate(files or [])
    ]
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
) -> PhotoListResponse:
    service = PhotoService(session)
    if entity_type and entity_id:
        photos, total = await service.list_for_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            kind=kind,
            actor=current_user,
        )
    else:
        photos, total = await service.list_recent(
            entity_type=entity_type,
            kind=kind,
            limit=limit,
            offset=offset,
            actor=current_user,
        )
    return PhotoListResponse(
        items=[PhotoResponse.model_validate(photo) for photo in photos],
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
) -> None:
    await PhotoService(session).delete(photo_id, current_user)


@router.post("/{photo_id}/recover", response_model=PhotoResponse)
async def recover_file(
    photo_id: UUID,
    current_user: CanViewReports,
    session: DbSession,
) -> PhotoResponse:
    if current_user.role != ROLE_ADMIN:
        from app.utils.exceptions import AppException

        raise AppException(
            "Only Admin can recover deleted photos.",
            status_code=403,
            error_code="PHOTO_RECOVERY_FORBIDDEN",
        )
    photo = await PhotoService(session).recover(photo_id, current_user)
    return PhotoResponse.model_validate(photo)
