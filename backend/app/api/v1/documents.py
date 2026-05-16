from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.dependencies import CurrentUser, DbSession
from app.schemas.documents import (
    DocumentDecisionRequest,
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
)
from app.services.document_service import SIGNED_URL_SECONDS, DocumentService

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: CurrentUser,
    session: DbSession,
    project_id: Annotated[UUID | None, Query()] = None,
    document_type: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
) -> DocumentListResponse:
    del current_user
    documents, total = await DocumentService(session).list_documents(
        project_id=project_id,
        document_type=document_type,
        search=search,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(document) for document in documents],
        total=total,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    current_user: CurrentUser,
    session: DbSession,
    title: Annotated[str, Form()],
    document_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    project_id: Annotated[UUID | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
) -> DocumentResponse:
    document = await DocumentService(session).upload_document(
        title=title,
        document_type=document_type,
        project_id=project_id,
        expiry_date=expiry_date,
        file=file,
        actor=current_user,
    )
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> DocumentResponse:
    del current_user
    document = await DocumentService(session)._get_required(document_id)
    return DocumentResponse.model_validate(document)


@router.post("/{document_id}/versions", response_model=DocumentResponse)
async def upload_document_version(
    document_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    document = await DocumentService(session).upload_version(document_id, file, current_user)
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/versions")
async def list_document_versions(
    document_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
) -> list:
    del current_user
    document = await DocumentService(session)._get_required(document_id)
    return [version for version in document.versions]


@router.post("/{document_id}/versions/{version_id}/approve", response_model=DocumentResponse)
async def approve_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentDecisionRequest,
    current_user: CurrentUser,
    session: DbSession,
) -> DocumentResponse:
    document = await DocumentService(session).approve_version(
        document_id,
        version_id,
        current_user,
        payload.comments,
    )
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/download", response_model=DocumentDownloadResponse)
async def get_document_download_url(
    document_id: UUID,
    current_user: CurrentUser,
    session: DbSession,
    version_id: Annotated[UUID | None, Query()] = None,
) -> DocumentDownloadResponse:
    url, superseded = await DocumentService(session).signed_download_url(
        document_id=document_id,
        version_id=version_id,
        actor=current_user,
    )
    return DocumentDownloadResponse(
        url=url,
        expires_in_seconds=SIGNED_URL_SECONDS,
        superseded_warning=superseded,
    )
