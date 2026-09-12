# app/modules/knowledge/router.py
"""
Knowledge documents router.

Admin CRUD is platform_admin-only. Public reads expose PUBLISHED documents
only — customer-facing content, same trust level as the public catalog.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_active_user
from app.modules.knowledge.service.base import KnowledgeService
from app.modules.knowledge.service.dependency import get_knowledge_service
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentPublicResponse,
    KnowledgeDocumentResponse,
    KnowledgeDocumentUpdate,
)

router = APIRouter()

get_current_active_user_depends = Depends(get_current_active_user)
get_knowledge_service_depends = Depends(get_knowledge_service)


def _require_platform_admin(current_user) -> None:
    if getattr(current_user.role, "value", current_user.role) != "platform_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only platform admins can manage knowledge documents")


@router.post("/documents", response_model=KnowledgeDocumentResponse, status_code=201)
async def create_document(
    data: KnowledgeDocumentCreate,
    current_user=Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """Create a knowledge document (starts as draft). platform_admin only."""
    _require_platform_admin(current_user)
    return await service.create_document(data, created_by=current_user.id)


@router.patch("/documents/{doc_id}", response_model=KnowledgeDocumentResponse)
async def update_document(
    doc_id: str,
    data: KnowledgeDocumentUpdate,
    current_user=Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """Update a document; content changes bump the version. platform_admin only."""
    _require_platform_admin(current_user)
    return await service.update_document(doc_id, data)


@router.delete("/documents/{doc_id}", response_model=KnowledgeDocumentResponse)
async def archive_document(
    doc_id: str,
    current_user=Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """Archive (soft-delete) a document. platform_admin only."""
    _require_platform_admin(current_user)
    return await service.archive_document(doc_id)


@router.get("/documents", response_model=list[KnowledgeDocumentResponse])
async def list_documents(
    current_user=Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
    status_filter: str | None = Query(None, alias="status"),
    doc_type: str | None = None,
    topic: str | None = None,
    skip: int = 0,
    limit: int = Query(100, le=200),
):
    """List documents with workflow fields. platform_admin only."""
    _require_platform_admin(current_user)
    return await service.list_documents(status=status_filter, doc_type=doc_type, topic=topic, skip=skip, limit=limit)


@router.get("/documents/{doc_id}", response_model=KnowledgeDocumentResponse)
async def get_document(
    doc_id: str,
    current_user=Depends(get_current_active_user),
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """Get one document with workflow fields. platform_admin only."""
    _require_platform_admin(current_user)
    doc = await service.get_document_admin(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return doc


# ── Public (published only) ──────────────────────────────────────────────
@router.get("/published", response_model=list[KnowledgeDocumentPublicResponse])
async def list_published_documents(
    service: KnowledgeService = Depends(get_knowledge_service),
    doc_type: str | None = None,
    topic: str | None = None,
    audience: str | None = None,
    skip: int = 0,
    limit: int = Query(100, le=200),
):
    """List published knowledge documents. Public — used by the agent's KB sync."""
    return await service.list_published(doc_type=doc_type, topic=topic, audience=audience, skip=skip, limit=limit)


@router.get("/published/{doc_id}", response_model=KnowledgeDocumentPublicResponse)
async def get_published_document(
    doc_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
):
    """Get one published document. Public."""
    doc = await service.get_published(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Published knowledge document not found")
    return doc


def get_router():
    return router
