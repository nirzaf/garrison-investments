"""Shared fail-closed classification rules for portal documents and media."""

from typing import Literal
from uuid import UUID

from app.models.user import User
from app.utils.exceptions import NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_FINANCIAL_VIEW,
    ensure_permission,
    has_permission,
)

EvidenceClassification = Literal["unclassified", "operational", "financial"]
UNCLASSIFIED = "unclassified"
OPERATIONAL = "operational"
FINANCIAL = "financial"


def ensure_evidence_classification_access(
    classification: str,
    uploaded_by: UUID | None,
    actor: User,
    *,
    financial_document: bool = False,
) -> None:
    """Apply classification after the owning document/project authorization succeeds."""
    if financial_document or classification == FINANCIAL:
        if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
            raise NotFoundException("Evidence")
        return
    if classification == OPERATIONAL:
        return
    if classification == UNCLASSIFIED and (
        uploaded_by == actor.id or has_permission(actor, PERMISSION_DOCUMENTS_MANAGE)
    ):
        return
    raise NotFoundException("Evidence")


def ensure_evidence_classification_reviewer(
    actor: User, uploaded_by: UUID | None, classification: EvidenceClassification
) -> None:
    ensure_permission(actor, PERMISSION_DOCUMENTS_MANAGE)
    if actor.id == uploaded_by:
        raise PermissionDeniedException("independent evidence classification review")
    if classification == FINANCIAL:
        ensure_permission(actor, PERMISSION_FINANCIAL_VIEW)
