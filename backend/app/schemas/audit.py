from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id: UUID
    user_id: UUID | None
    event_type: str
    severity: str
    action: str
    entity_type: str | None
    entity_id: UUID | None
    request_id: str | None
    session_id: str | None
    ip_address: str | None
    endpoint: str | None
    http_method: str | None
    status_code: int | None
    source_service: str | None
    instance_id: str | None
    storage_tier: str
    archived_at: datetime | None
    retention_until: datetime | None
    user_agent: str | None
    comments: str | None
    context_payload: dict | None
    old_values: dict | None
    new_values: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
