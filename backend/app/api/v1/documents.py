from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile, status

from app.api.dependencies import CurrentUser, DbSession, require_permission
from app.models.user import User
from app.schemas.documents import (
    DocumentDecisionRequest,
    DocumentDownloadResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentVersionResponse,
    EvidenceClassificationRequest,
)
from app.schemas.projects import ProjectOption, ProjectOptionListResponse
from app.services.document_service import SIGNED_URL_SECONDS, DocumentService
from app.services.idempotency import validate_key
from app.services.project_service import ProjectService
from app.utils.permissions import PERMISSION_DOCUMENTS_MANAGE, PERMISSION_DOCUMENTS_VIEW

router = APIRouter(prefix="/documents", tags=["Documents"])
CanManageDocuments = Annotated[User, Depends(require_permission(PERMISSION_DOCUMENTS_MANAGE))]
CanViewDocuments = Annotated[User, Depends(require_permission(PERMISSION_DOCUMENTS_VIEW))]


@router.get("/project-options", response_model=ProjectOptionListResponse)
async def list_document_project_options(
    current_user: CurrentUser,
    session: DbSession,
    search: Annotated[str | None, Query(max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectOptionListResponse:
    projects, total = await ProjectService(session).list_document_project_options(
        current_user, search=search, limit=limit, offset=offset
    )
    return ProjectOptionListResponse(
        items=[ProjectOption.model_validate(project) for project in projects], total=total
    )


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    current_user: CanViewDocuments,
    session: DbSession,
    response: Response,
    project_id: Annotated[UUID | None, Query()] = None,
    document_type: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    response.headers["Cache-Control"] = "no-store"
    documents, total = await DocumentService(session).list_documents(
        project_id=project_id,
        document_type=document_type,
        search=search,
        limit=limit,
        offset=offset,
        actor=current_user,
    )
    return DocumentListResponse(
        items=[DocumentResponse.model_validate(document) for document in documents],
        total=total,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    current_user: CanManageDocuments,
    session: DbSession,
    response: Response,
    title: Annotated[str, Form()],
    document_type: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    project_id: Annotated[UUID | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
) -> DocumentResponse:
    response.headers["Cache-Control"] = "no-store"
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
    current_user: CanViewDocuments,
    session: DbSession,
    response: Response,
) -> DocumentResponse:
    response.headers["Cache-Control"] = "no-store"
    document = await DocumentService(session).get(document_id, current_user)
    return DocumentResponse.model_validate(document)


@router.post("/{document_id}/versions", response_model=DocumentResponse)
async def upload_document_version(
    document_id: UUID,
    current_user: CanManageDocuments,
    session: DbSession,
    response: Response,
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DocumentResponse:
    response.headers["Cache-Control"] = "no-store"
    document = await DocumentService(session).upload_version(
        document_id, file, current_user, validate_key(idempotency_key)
    )
    return DocumentResponse.model_validate(document)


@router.get("/{document_id}/versions", response_model=list[DocumentVersionResponse])
async def list_document_versions(
    document_id: UUID,
    current_user: CanViewDocuments,
    session: DbSession,
    response: Response,
) -> list[DocumentVersionResponse]:
    response.headers["Cache-Control"] = "no-store"
    versions = await DocumentService(session).list_document_versions(document_id, current_user)
    return [DocumentVersionResponse.model_validate(version) for version in versions]


@router.post("/{document_id}/versions/{version_id}/approve", response_model=DocumentResponse)
async def approve_document_version(
    document_id: UUID,
    version_id: UUID,
    payload: DocumentDecisionRequest,
    current_user: CanManageDocuments,
    session: DbSession,
    response: Response,
) -> DocumentResponse:
    response.headers["Cache-Control"] = "no-store"
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
    response: Response,
    current_user: CanViewDocuments,
    session: DbSession,
    version_id: Annotated[UUID | None, Query()] = None,
) -> DocumentDownloadResponse:
    url, superseded = await DocumentService(session).signed_download_url(
        document_id=document_id,
        version_id=version_id,
        actor=current_user,
    )
    response.headers["Cache-Control"] = "no-store"
    return DocumentDownloadResponse(
        url=url,
        expires_in_seconds=SIGNED_URL_SECONDS,
        superseded_warning=superseded,
    )


@router.patch("/{document_id}/classification", response_model=DocumentResponse)
async def classify_document(
    document_id: UUID,
    payload: EvidenceClassificationRequest,
    current_user: CurrentUser,
    session: DbSession,
    response: Response,
) -> DocumentResponse:
    response.headers["Cache-Control"] = "no-store"
    document = await DocumentService(session).classify_document(
        document_id, payload.classification, payload.reason, current_user
    )
    return DocumentResponse.model_validate(document)
