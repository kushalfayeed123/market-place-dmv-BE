# app/modules/knowledge/service/implementation.py
"""Database-backed implementation of the knowledge document service."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import (
    DocAudience,
    DocStatus,
    DocType,
    KnowledgeDocument,
)
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentPublicResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdate,
)
from app.modules.knowledge.service.base import KnowledgeService


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


class KnowledgeServiceImpl(KnowledgeService):
    """SQLAlchemy implementation. Version bumps on content edits."""

    def __init__(self, db: AsyncSession):
        self._db = db

    def _to_response(self, doc: KnowledgeDocument) -> KnowledgeDocumentResponse:
        return KnowledgeDocumentResponse(
            id=str(doc.id), doc_type=doc.doc_type.value, title=doc.title, body=doc.body,
            topic=doc.topic, audience=doc.audience.value, status=doc.status.value,
            version=str(doc.version), effective_from=doc.effective_from,
            effective_to=doc.effective_to, created_at=doc.created_at, updated_at=doc.updated_at,
        )

    def _to_public(self, doc: KnowledgeDocument) -> KnowledgeDocumentPublicResponse:
        return KnowledgeDocumentPublicResponse(
            id=str(doc.id), doc_type=doc.doc_type.value, title=doc.title, body=doc.body,
            topic=doc.topic, audience=doc.audience.value, version=str(doc.version),
            effective_from=doc.effective_from, updated_at=doc.updated_at,
        )

    async def create_document(self, data: KnowledgeDocumentCreate, created_by) -> KnowledgeDocumentResponse:
        doc = KnowledgeDocument(
            doc_type=DocType(data.doc_type.value),
            title=data.title,
            body=data.body,
            topic=data.topic,
            audience=DocAudience(data.audience.value),
            status=DocStatus.DRAFT,
            version="1",
            effective_from=data.effective_from,
            effective_to=data.effective_to,
            created_by=created_by,
        )
        self._db.add(doc)
        await self._db.commit()
        await self._db.refresh(doc)
        return self._to_response(doc)

    async def update_document(self, doc_id: str, data: KnowledgeDocumentUpdate) -> KnowledgeDocumentResponse:
        doc = await self._get_or_404(doc_id)
        content_changed = False
        for field, value in data.model_dump(exclude_unset=True).items():
            if value is None:
                continue
            if field in ("doc_type", "audience", "status"):
                value = _enum_value(value)
            if field in ("title", "body") and getattr(doc, field) != value:
                content_changed = True
            setattr(doc, field, value)
        if content_changed:
            doc.version = str(int(doc.version) + 1)
        await self._db.commit()
        await self._db.refresh(doc)
        return self._to_response(doc)

    async def archive_document(self, doc_id: str) -> KnowledgeDocumentResponse:
        doc = await self._get_or_404(doc_id)
        doc.status = DocStatus.ARCHIVED
        await self._db.commit()
        await self._db.refresh(doc)
        return self._to_response(doc)

    async def list_documents(
        self, *, status: str | None = None, doc_type: str | None = None, topic: str | None = None,
        skip: int = 0, limit: int = 100,
    ) -> list[KnowledgeDocumentResponse]:
        query = select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())
        if status:
            query = query.where(KnowledgeDocument.status == DocStatus(status))
        if doc_type:
            query = query.where(KnowledgeDocument.doc_type == DocType(doc_type))
        if topic:
            query = query.where(KnowledgeDocument.topic == topic)
        result = await self._db.execute(query.offset(skip).limit(limit))
        return [self._to_response(d) for d in result.scalars().all()]

    async def get_document_admin(self, doc_id: str) -> KnowledgeDocumentResponse | None:
        doc = await self._get_or_none(doc_id)
        return self._to_response(doc) if doc else None

    async def list_published(
        self, *, doc_type: str | None = None, topic: str | None = None,
        audience: str | None = None, skip: int = 0, limit: int = 100,
    ) -> list[KnowledgeDocumentPublicResponse]:
        query = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.status == DocStatus.PUBLISHED)
            .order_by(KnowledgeDocument.updated_at.desc())
        )
        if doc_type:
            query = query.where(KnowledgeDocument.doc_type == DocType(doc_type))
        if topic:
            query = query.where(KnowledgeDocument.topic == topic)
        if audience:
            query = query.where(KnowledgeDocument.audience == DocAudience(audience))
        result = await self._db.execute(query.offset(skip).limit(limit))
        return [self._to_public(d) for d in result.scalars().all()]

    async def get_published(self, doc_id: str) -> KnowledgeDocumentPublicResponse | None:
        from app.core.security import to_uuid

        result = await self._db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == to_uuid(doc_id),
                KnowledgeDocument.status == DocStatus.PUBLISHED,
            )
        )
        doc = result.scalar_one_or_none()
        return self._to_public(doc) if doc else None

    async def _get_or_404(self, doc_id: str) -> KnowledgeDocument:
        from fastapi import HTTPException, status as http_status

        doc = await self._get_or_none(doc_id)
        if doc is None:
            raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
        return doc

    async def _get_or_none(self, doc_id: str) -> KnowledgeDocument | None:
        from app.core.security import to_uuid

        return await self._db.get(KnowledgeDocument, to_uuid(doc_id))

