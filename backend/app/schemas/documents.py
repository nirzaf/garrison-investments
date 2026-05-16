from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version: int
    status: str
    storage_path: str
    original_name: str
    mime_type: str
    size_bytes: int
    uploaded_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    approval_comments: str | None

    model_config = ConfigDict(from_attributes=True)


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    document_type: str
    project_id: UUID | None
    status: str
    active_version: int | None
    metadata_json: dict[str, Any]
    expiry_date: date | None
    uploaded_by: UUID | None
    versions: list[DocumentVersionResponse]

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int


class DocumentDecisionRequest(BaseModel):
    comments: str | None = None


class DocumentDownloadResponse(BaseModel):
    url: str
    expires_in_seconds: int
    superseded_warning: bool
