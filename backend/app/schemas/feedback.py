from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

FeedbackCategory = Literal["bug", "suggestion", "other"]
FeedbackStatus = Literal["new", "investigating", "resolved"]
RequestReference = Annotated[
    str, StringConstraints(pattern=r"^[a-f0-9]{32}$|^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")
]


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission_id: UUID
    category: FeedbackCategory
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=140)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=4000)
    ]
    request_ids: list[RequestReference] = Field(default_factory=list, max_length=8)


class FeedbackReceipt(BaseModel):
    id: UUID
    created_at: datetime
    attached_diagnostics: int


class FeedbackDiagnostic(BaseModel):
    request_id: RequestReference
    occurred_at: datetime
    area: str
    method: str
    status_code: int


class FeedbackInboxItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reporter_id: UUID | None
    category: FeedbackCategory
    title: str
    description: str
    status: FeedbackStatus
    revision: int
    created_at: datetime
    updated_at: datetime
    diagnostics: list[FeedbackDiagnostic]


class FeedbackInboxPage(BaseModel):
    items: list[FeedbackInboxItem]
    has_more: bool


class FeedbackStatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FeedbackStatus
    expected_revision: int = Field(ge=1)
