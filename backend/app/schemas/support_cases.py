from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

CaseReason = Literal["availability", "access", "functional", "data_integrity"]
CaseSeverity = Literal["low", "medium", "high", "critical"]
CaseStatus = Literal["open", "investigating", "mitigated", "verified", "closed"]


class SupportCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_ref: Annotated[
        str, StringConstraints(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    ]
    severity: CaseSeverity
    reason_code: CaseReason


class SupportCaseTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["investigating", "mitigated"]
    reason_code: CaseReason


class SupportCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    external_ref: str
    owner_id: UUID
    status: CaseStatus
    severity: CaseSeverity
    reason_code: CaseReason
    revision: int
    created_at: datetime
    updated_at: datetime


class SupportCasePage(BaseModel):
    items: list[SupportCaseRead]
    next_cursor: str | None
