from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

CaseActionKind = Literal[
    "member_add",
    "member_remove",
    "evidence_link",
    "verify",
    "close",
    "subject_set",
    "subject_remove",
    "project_add",
    "project_remove",
]
MEMBERSHIP_ACTIONS = {"member_add", "member_remove"}
SOURCE_ACTIONS = {"evidence_link", "verify"}
SUBJECT_ACTIONS = {"subject_set", "subject_remove"}
PROJECT_ACTIONS = {"project_add", "project_remove"}
MAX_CASE_PROJECTS = 10


class CaseActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CaseActionKind
    member_id: UUID | None = None
    source_event_id: UUID | None = None
    subject_user_id: UUID | None = None
    project_id: UUID | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if (self.kind in MEMBERSHIP_ACTIONS) != (self.member_id is not None) or (
            self.kind in SOURCE_ACTIONS
        ) != (self.source_event_id is not None):
            raise ValueError("Provide the member or source event required by the selected action.")
        if (self.kind == "subject_set") != (self.subject_user_id is not None):
            raise ValueError("An account reference is required only when setting the case account.")
        if (self.kind in PROJECT_ACTIONS) != (self.project_id is not None):
            raise ValueError("A project reference is required only for project scope actions.")
        return self


class CaseActionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    case_id: UUID
    kind: CaseActionKind
    member_id: UUID | None
    source_event_id: UUID | None
    subject_user_id: UUID | None
    project_id: UUID | None
    source_request_id: str | None
    source_status: int | None
    case_revision: int
    expires_at: datetime
    reviewer_id: UUID | None
    applied_at: datetime | None
