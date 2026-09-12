# app/modules/knowledge/service/base.py
"""Abstract interface for the knowledge document service."""

from abc import ABC, abstractmethod

from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentPublicResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdate,
)


class KnowledgeService(ABC):
    """Contract for knowledge document operations (admin CRUD + public read)."""

    @abstractmethod
    async def create_document(self, data: KnowledgeDocumentCreate, created_by) -> KnowledgeDocumentResponse: ...

    @abstractmethod
    async def update_document(self, doc_id: str, data: KnowledgeDocumentUpdate) -> KnowledgeDocumentResponse: ...

    @abstractmethod
    async def archive_document(self, doc_id: str) -> KnowledgeDocumentResponse:
        """Soft-delete: set status=archived (history retained)."""

    @abstractmethod
    async def list_documents(
        self, *, status: str | None = None, doc_type: str | None = None, topic: str | None = None,
        skip: int = 0, limit: int = 100,
    ) -> list[KnowledgeDocumentResponse]: ...

    @abstractmethod
    async def get_document_admin(self, doc_id: str) -> KnowledgeDocumentResponse | None: ...

    # ── Public (published only) ──────────────────────────────────────────
    @abstractmethod
    async def list_published(
        self, *, doc_type: str | None = None, topic: str | None = None,
        audience: str | None = None, skip: int = 0, limit: int = 100,
    ) -> list[KnowledgeDocumentPublicResponse]: ...

    @abstractmethod
    async def get_published(self, doc_id: str) -> KnowledgeDocumentPublicResponse | None: ...
