from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PhotoResponse(BaseModel):
    id: UUID
    filename: str | None = None
    original_name: str | None = None
    storage_path: str | None = None
    compressed_path: str | None = None
    thumbnail_path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    entity_type: str
    entity_id: UUID
    kind: str
    classification: Literal["unclassified", "operational", "financial"]
    caption: str | None = None
    taken_at: datetime | None = None
    uploaded_by: UUID | None
    processing_status: str
    can_delete: bool = False
    deleted_at: datetime | None = None
    recoverable_until: datetime | None = None
    restricted: bool = False
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PhotoListResponse(BaseModel):
    items: list[PhotoResponse]
    total: int


class PhotoDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class ProtectedFileUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
