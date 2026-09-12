# app/models/knowledge_document.py
"""
KnowledgeDocument model — admin-curated knowledge base content.

This is a plain business feature (policies/FAQs/guides), NOT AI-aware:
the agent merely consumes the public published view like any other client.
"""

from enum import Enum as PyEnum

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.db.types import UUID, ENUM as PgEnum


class DocType(PyEnum):
    POLICY = "policy"
    FAQ = "faq"
    GUIDE = "guide"
    ANNOUNCEMENT = "announcement"


class DocStatus(PyEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class DocAudience(PyEnum):
    BUYER = "buyer"
    MERCHANT = "merchant"
    ALL = "all"


class KnowledgeDocument(BaseModel):
    __tablename__ = "knowledge_documents"

    doc_type = Column(PgEnum(DocType), nullable=False, default=DocType.POLICY)
    # VARCHAR(255): indexed column; MySQL cannot index TEXT without prefix length
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)  # markdown
    # single-col index intentionally omitted: covered by idx_knowledge_documents_topic
    topic = Column(String(100), nullable=True)
    audience = Column(PgEnum(DocAudience), nullable=False, default=DocAudience.ALL)
    status = Column(PgEnum(DocStatus), nullable=False, default=DocStatus.DRAFT, index=True)
    # Bumped on content edits so agent citations can reference a specific version
    version = Column(String(20), nullable=False, server_default="1")
    effective_from = Column(DateTime(timezone=True), nullable=True)
    effective_to = Column(DateTime(timezone=True), nullable=True)
    # index=True: InnoDB requires an index on every FK column; declaring it
    # explicitly keeps model metadata in parity with the MySQL schema
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    __table_args__ = (
        Index("idx_knowledge_documents_type_status", doc_type, status),
        Index("idx_knowledge_documents_topic", topic),
    )

    def __repr__(self):
        return f"<KnowledgeDocument(id={self.id}, title={self.title}, status={self.status.value})>"
