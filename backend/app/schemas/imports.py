from uuid import UUID

from pydantic import BaseModel


class ImportErrorItem(BaseModel):
    row: int
    field: str
    message: str


class ImportPreviewResponse(BaseModel):
    template_type: str
    row_count: int
    errors: list[ImportErrorItem]
    valid: bool


class ImportRunResponse(BaseModel):
    batch_id: UUID
    template_type: str
    file_name: str | None = None
    status: str
    row_count: int
    error_count: int
    summary: dict


class ImportBatchListResponse(BaseModel):
    items: list[ImportRunResponse]
    total: int
