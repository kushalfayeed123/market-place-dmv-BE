# app/modules/documents/router.py
"""
Documents router — S3-backed upload and retrieval endpoints.

Endpoints (all under ``/api/v1/documents``):

* ``GET  /uploads``            — presigned POST for browser-to-S3 upload
* ``POST /complete``           — finalize upload (idempotent)
* ``GET  /``                   — list documents (merchant-scoped)
* ``GET  /{id}``               — get a single document
* ``GET  /{id}/download-url``  — short-lived presigned download URL (300 s)
* ``DELETE /{id}``             — soft-delete a document

Security: unauthorized reads return **404** (not 403) to prevent existence
disclosure.  Download URLs are generated on-demand and never persisted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.documents.deps import get_merchant_id
from app.modules.documents.service import DocumentService
from app.schemas.document import (
    DocumentCompleteRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
    DocumentDownloadUrlResponse,
)

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in defaults)
get_db_depends = Depends(get_db)
get_merchant_id_depends = Depends(get_merchant_id)


def get_document_service(db: AsyncSession = get_db_depends) -> DocumentService:
    """Factory dependency that injects the document service."""
    return DocumentService(db)


@router.get("/uploads", response_model=DocumentUploadResponse)
async def presign_upload_endpoint(
    payload: DocumentUploadRequest = Depends(),
    merchant_id: str = get_merchant_id_depends,
    db: AsyncSession = get_db_depends,
):
    """
    Request presigned POST fields for a new document upload.

    The caller (browser) POSTs the actual file bytes directly to S3 using
    the returned ``upload_url`` and ``upload_fields``.
    """
    service = DocumentService(db)
    return await service.create_presigned_upload(
        merchant_id_str=str(merchant_id),
        payload=payload,
    )


@router.post("/complete", response_model=DocumentResponse)
async def complete_upload_endpoint(
    request: DocumentCompleteRequest,
    merchant_id: str = get_merchant_id_depends,
    db: AsyncSession = get_db_depends,
):
    """
    Finalize a document upload after the browser has POSTed to S3.

    Verifies the object exists in S3, checks magic bytes, and transitions the
    document from ``PENDING`` to ``COMPLETE``.  Idempotent — calling this on
    an already-complete document returns the existing record.
    """
    service = DocumentService(db)
    return await service.complete_upload(request)


@router.get("/", response_model=DocumentListResponse)
async def list_documents_endpoint(
    merchant_id: str = get_merchant_id_depends,
    purpose: str | None = Query(None, description="Filter by document purpose."),
    related_type: str | None = Query(None, description="Filter by related_type."),
    related_id: str | None = Query(None, description="Filter by related_id."),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = get_db_depends,
):
    """List documents belonging to the current merchant (or all for admin)."""
    service = DocumentService(db)
    return await service.list_documents(
        merchant_id_str=str(merchant_id),
        purpose=purpose,
        related_type=related_type,
        related_id=related_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document_endpoint(
    doc_id: str,
    merchant_id: str = get_merchant_id_depends,
    db: AsyncSession = get_db_depends,
):
    """Retrieve a single document by id.  404 if not found / unauthorized."""
    service = DocumentService(db)
    return await service.get_document(str(merchant_id), doc_id)


@router.get("/{doc_id}/download-url", response_model=DocumentDownloadUrlResponse)
async def get_download_url_endpoint(
    doc_id: str,
    merchant_id: str = get_merchant_id_depends,
    db: AsyncSession = get_db_depends,
):
    """
    Get a short-lived presigned download URL for a document.

    * Public documents (CDN-backed) return a permanent URL (``expires_in=0``).
    * Private documents return a presigned URL expiring in 300 s.
    * The URL is generated on-demand and **never stored** in the database.
    """
    service = DocumentService(db)
    url, ttl = await service.get_download_url(str(merchant_id), doc_id)
    return DocumentDownloadUrlResponse(download_url=url, expires_in=ttl)


@router.delete("/{doc_id}")
async def delete_document_endpoint(
    doc_id: str,
    merchant_id: str = get_merchant_id_depends,
    db: AsyncSession = get_db_depends,
):
    """
    Soft-delete a document (mark ``deleted_at`` and remove from S3).

    Returns a 204 No Content on success.
    """
    service = DocumentService(db)
    await service.delete_document(str(merchant_id), doc_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
