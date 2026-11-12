from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApprovalCreateRequest(BaseModel):
    request_type: str = Field(min_length=2, max_length=60)
    request_id: UUID
    project_id: UUID | None = None
    title: str = Field(min_length=2, max_length=200)
    amount: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    comments: str | None = Field(default=None, max_length=2000)


class ApprovalDecisionRequest(BaseModel):
    comments: str | None = Field(default=None, max_length=2000)


class ApprovalDelegationRequest(BaseModel):
    delegated_to_id: UUID
    reason: str = Field(min_length=3, max_length=2000)


class ApprovalOverrideRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    reason: str = Field(min_length=3, max_length=2000)


class ApprovalResponse(BaseModel):
    id: UUID
    request_type: str
    request_id: UUID
    project_id: UUID | None
    submitter_id: UUID | None
    approver_id: UUID | None
    delegated_to_id: UUID | None
    escalation_user_id: UUID | None
    status: str
    step_order: int
    amount: Decimal | None
    currency: str | None
    title: str
    submitter_comments: str | None
    decision_comments: str | None
    delegation_reason: str | None
    override_reason: str | None
    submitted_at: datetime
    due_at: datetime
    reminded_at: datetime | None
    escalated_at: datetime | None
    decided_at: datetime | None
    allowed_actions: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class ApprovalListResponse(BaseModel):
    items: list[ApprovalResponse]
    total: int


class ApprovalDelegateResponse(BaseModel):
    """Minimal identity for the delegation picker — no account or security fields."""

    id: UUID
    full_name: str
    role: str

    model_config = ConfigDict(from_attributes=True)


class ApprovalDelegateListResponse(BaseModel):
    items: list[ApprovalDelegateResponse]
    total: int
