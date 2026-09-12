# app/schemas/knowledge.py
"""
Pydantic schemas for the knowledge document module.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from pydantic import BaseModel, Field


class DocType(str, PyEnum):
    POLICY = "policy"
    FAQ = "faq"
    GUIDE = "guide"
    ANNOUNCEMENT = "announcement"


class DocStatus(str, PyEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class DocAudience(str, PyEnum):
    BUYER = "buyer"
    MERCHANT = "merchant"
    ALL = "all"


class KnowledgeDocumentCreate(BaseModel):
    doc_type: DocType = DocType.POLICY
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    topic: Optional[str] = Field(None, max_length=100)
    audience: DocAudience = DocAudience.ALL
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None


class KnowledgeDocumentUpdate(BaseModel):
    """Partial update. Content changes (title/body) bump the version."""

    doc_type: Optional[DocType] = None
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    body: Optional[str] = Field(None, min_length=1)
    topic: Optional[str] = Field(None, max_length=100)
    audience: Optional[DocAudience] = None
    status: Optional[DocStatus] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None


class KnowledgeDocumentResponse(BaseModel):
    id: str
    doc_type: str
    title: str
    body: str
    topic: Optional[str] = None
    audience: str
    status: str
    version: str
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeDocumentPublicResponse(BaseModel):
    """Public (published-only) view — excludes workflow fields."""

    id: str
    doc_type: str
    title: str
    body: str
    topic: Optional[str] = None
    audience: str
    version: str
    effective_from: Optional[datetime] = None
    updated_at: datetime

    model_config = {"from_attributes": True}
