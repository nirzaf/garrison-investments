from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

BusinessActionKind = Literal[
    "revoke_sessions", "unlock", "disable", "reactivate", "permission_view", "recover",
    "request_summary", "navigation_view", "project_list", "project_detail",
]
BusinessActionStage = Literal["review", "execute"]
ActionDigest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class BusinessActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: BusinessActionKind
    user_id: UUID
    user_revision: int = Field(ge=0, strict=True)
    case_revision: int = Field(ge=1, strict=True)
    reason_code: Literal[
        "suspected_access", "verified_user_report", "failed_sign_in", "permission_triage",
        "request_triage",
    ]
    permission_key: Annotated[str, StringConstraints(min_length=1, max_length=64)] | None = None
    source_event_id: UUID | None = None
    project_id: UUID | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=300)]

    @model_validator(mode="after")
    def match_permission_view(self) -> Self:
        if (self.permission_key is not None) != (self.kind == "permission_view"):
            raise ValueError("A permission key is required only for a permission view.")
        if (self.source_event_id is not None) != (self.kind == "request_summary"):
            raise ValueError("A source event is required only for a request summary.")
        if (self.project_id is not None) != (self.kind == "project_detail"):
            raise ValueError("A project reference is required only for a project detail view.")
        return self


class BusinessActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    user_id: UUID
    user_revision: int
    case_revision: int
    kind: BusinessActionKind
    reason_code: str
    permission_key: str | None
    source_event_id: UUID | None
    project_id: UUID | None
    reason: str
    digest: ActionDigest
    expires_at: datetime
    applied_at: datetime | None


RecoveryDeliveryState = Literal[
    "not_queued", "pending", "dispatching", "accepted", "unknown", "cancelled"
]
RecoveryResetState = Literal[
    "not_issued", "waiting", "ready", "unavailable", "completed", "expired", "revoked"
]


class SupportRecoveryStatus(BaseModel):
    case_id: UUID
    action_id: UUID
    delivery_state: RecoveryDeliveryState
    reset_state: RecoveryResetState
    queued_at: datetime | None = None
    delivery_resolved_at: datetime | None = None
    completed_at: datetime | None = None
