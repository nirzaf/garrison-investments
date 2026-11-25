from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models.document import Document, DocumentVersion


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_document(self, document: Document) -> Document:
        self.session.add(document)
        await self.session.flush()
        return document

    async def add_version(self, version: DocumentVersion) -> DocumentVersion:
        self.session.add(version)
        await self.session.flush()
        return version

    async def get_document(self, document_id: UUID) -> Document | None:
        result = await self.session.execute(
            self._with_versions().where(Document.id == document_id, Document.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def lock_document(self, document_id: UUID) -> Document | None:
        """Plain parent-row lock; versions are selectinload, so they are not locked.

        Call ``get_document`` afterwards to obtain the same identity-mapped instance
        with its versions loaded.
        """
        result = await self.session.execute(
            select(Document)
            .where(Document.id == document_id, Document.deleted_at.is_(None))
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_version(self, version_id: UUID) -> DocumentVersion | None:
        result = await self.session.execute(
            select(DocumentVersion).where(
                DocumentVersion.id == version_id,
                DocumentVersion.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def next_version(self, document_id: UUID) -> int:
        value = await self.session.scalar(
            select(func.max(DocumentVersion.version)).where(
                DocumentVersion.document_id == document_id,
            )
        )
        return int(value or 0) + 1

    async def list_documents(
        self,
        *,
        project_id: UUID | None,
        document_type: str | None,
        search: str | None,
        limit: int,
        offset: int,
        scope_filter: ColumnElement[bool] | None = None,
        classification_filter: ColumnElement[bool] | None = None,
        exclude_document_types: set[str] | None = None,
    ) -> tuple[list[Document], int]:
        query: Select = self._with_versions().where(Document.deleted_at.is_(None))
        if scope_filter is not None:
            query = query.where(scope_filter)
        if classification_filter is not None:
            query = query.where(classification_filter)
        if exclude_document_types:
            query = query.where(
                func.lower(func.trim(Document.document_type)).notin_(
                    {value.lower() for value in exclude_document_types}
                )
            )
        if project_id:
            query = query.where(Document.project_id == project_id)
        if document_type:
            query = query.where(
                func.lower(func.trim(Document.document_type)) == document_type.strip().lower()
            )
        if search:
            clean = search.strip()
            if clean:
                query = query.where(
                    func.to_tsvector("english", Document.title).bool_op("@@")(
                        func.plainto_tsquery("english", clean)
                    )
                )
        total = await self.session.scalar(
            select(func.count()).select_from(query.with_only_columns(Document.id).subquery())
        )
        result = await self.session.execute(
            query.order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().unique().all()), int(total or 0)

    def _with_versions(self) -> Select:
        return select(Document).options(selectinload(Document.versions))
