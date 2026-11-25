"""Shared fail-closed classification rules for portal documents and media."""

from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.document import Document, DocumentVersion
from app.models.photo import Photo
from app.models.user import User
from app.utils.exceptions import NotFoundException, PermissionDeniedException
from app.utils.permissions import (
    COMPANY_RESOURCE_ROLES,
    PERMISSION_DOCUMENTS_MANAGE,
    PERMISSION_FINANCIAL_VIEW,
    ensure_permission,
    has_permission,
)

EvidenceClassification = Literal["unclassified", "operational", "financial"]
UNCLASSIFIED: EvidenceClassification = "unclassified"
OPERATIONAL: EvidenceClassification = "operational"
FINANCIAL: EvidenceClassification = "financial"


def effective_document_classification(document: Document) -> EvidenceClassification:
    """A retained version can only make its parent more restrictive."""
    rank = {OPERATIONAL: 0, UNCLASSIFIED: 1, FINANCIAL: 2}
    classifications = [document.classification]
    classifications.extend(version.classification for version in document.versions)
    return max(classifications, key=rank.__getitem__)


def operational_document_predicate() -> ColumnElement[bool]:
    restricted_version = (
        select(DocumentVersion.id)
        .where(
            DocumentVersion.document_id == Document.id,
            DocumentVersion.classification != OPERATIONAL,
        )
        .exists()
    )
    return and_(
        Document.classification == OPERATIONAL,
        func.lower(func.trim(Document.document_type)).notin_({"contract", "invoice"}),
        not_(restricted_version),
    )


def ensure_evidence_classification_access(
    classification: str,
    uploaded_by: UUID | None,
    actor: User,
    *,
    financial_document: bool = False,
) -> None:
    """Apply classification after the owning document/project authorization succeeds."""
    if financial_document or classification in {FINANCIAL, UNCLASSIFIED}:
        if not has_permission(actor, PERMISSION_FINANCIAL_VIEW):
            raise NotFoundException("Evidence")
        return
    if classification == OPERATIONAL:
        return
    raise NotFoundException("Evidence")


def ensure_evidence_classification_reviewer(
    actor: User, uploaded_by: UUID | None, classification: EvidenceClassification
) -> None:
    ensure_permission(actor, PERMISSION_DOCUMENTS_MANAGE)
    if actor.role not in COMPANY_RESOURCE_ROLES or not has_permission(
        actor, PERMISSION_FINANCIAL_VIEW
    ):
        raise PermissionDeniedException("review evidence classification")
    if actor.id == uploaded_by:
        raise PermissionDeniedException("independent evidence classification review")
    if classification == FINANCIAL:
        ensure_permission(actor, PERMISSION_FINANCIAL_VIEW)


async def readable_photo_ids(
    session: AsyncSession, photo_ids: list[UUID], actor: User
) -> list[UUID]:
    """Filter history references using the same fail-closed policy as media reads."""
    if not photo_ids:
        return []
    if has_permission(actor, PERMISSION_FINANCIAL_VIEW):
        return photo_ids
    operational_document = (
        select(Document.id)
        .where(
            Document.id == Photo.entity_id,
            Document.deleted_at.is_(None),
            operational_document_predicate(),
        )
        .exists()
    )
    rows = await session.scalars(
        select(Photo.id).where(
            Photo.id.in_(photo_ids),
            Photo.deleted_at.is_(None),
            Photo.classification == OPERATIONAL,
            or_(Photo.entity_type != "document", operational_document),
        )
    )
    readable = set(rows)
    return [photo_id for photo_id in photo_ids if photo_id in readable]


async def readable_document_ids(
    session: AsyncSession, document_ids: list[UUID], actor: User
) -> list[UUID]:
    if not document_ids:
        return []
    if has_permission(actor, PERMISSION_FINANCIAL_VIEW):
        return document_ids
    rows = await session.scalars(
        select(Document.id).where(
            Document.id.in_(document_ids),
            Document.deleted_at.is_(None),
            operational_document_predicate(),
        )
    )
    readable = set(rows)
    return [document_id for document_id in document_ids if document_id in readable]
