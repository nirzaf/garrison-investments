from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PhotoResponse(BaseModel):
    id: UUID
    filename: str
    original_name: str
    storage_path: str
    compressed_path: str | None
    thumbnail_path: str | None
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    entity_type: str
    entity_id: UUID
    kind: str
    caption: str | None
    taken_at: datetime | None
    uploaded_by: UUID | None
    processing_status: str

    model_config = ConfigDict(from_attributes=True)


class PhotoListResponse(BaseModel):
    items: list[PhotoResponse]
    total: int


class ProtectedFileUrlResponse(BaseModel):
    url: str
    expires_in_seconds: int
