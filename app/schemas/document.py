# app/schemas/document.py
"""
Pydantic request/response schemas for the documents subsystem.

Endpoints (all under ``/api/v1/documents``):

GET    /uploads             — presigned POST fields for browser upload
POST   /complete            — mark a document complete (idempotent)
GET    /                  — list documents
GET    /{id}              — get a single document
GET    /{id}/download-url — short-lived presigned download URL
DELETE /{id}              — soft-delete a document

Security note: unauthorized reads return **404** (not 403) to avoid
existence disclosure.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────────────────


class DocumentUploadRequest(BaseModel):
    """Body for POST ``/documents/uploads`` — ask for a presigned POST URL."""

    purpose: str = Field(..., description="Document purpose, e.g. 'kyc', 'product_image'.")
    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1, max_length=128)
    size_bytes: int = Field(..., gt=0, description="Expected file size in bytes.")
    # Optional FK linkage — validated by the service against the purpose.
    related_type: str | None = Field(None, max_length=64)
    related_id: str | None = Field(None, max_length=64)

    model_config = {"extra": "forbid"}


class DocumentCompleteRequest(BaseModel):
    """Body for POST ``/documents/complete`` — finalize an upload."""

    # The client must echo back the exact ``key`` it received from presign.
    key: str = Field(..., min_length=1)
    # Optional MD5 / ETag checksum sent by the browser for integrity check.
    checksum: str | None = Field(None, max_length=128)

    model_config = {"extra": "forbid"}


# ── Response schemas ────────────────────────────────────────────────────


class DocumentUploadResponse(BaseModel):
    """Presigned POST payload returned to the browser for the S3 form."""

    document_id: str
    upload_url: str  # S3 POST endpoint
    upload_fields: dict[str, Any]  # form fields for the POST
    key: str  # the object key that was reserved
    max_size_bytes: int
    ttl_seconds: int


class DocumentResponse(BaseModel):
    """Full document record returned to the caller."""

    id: str
    purpose: str
    merchant_id: str | None = None
    filename: str
    content_type: str
    size_bytes: int
    object_key: str
    status: str
    public: bool
    related_type: str | None = None
    related_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDownloadUrlResponse(BaseModel):
    """Short-lived presigned download URL (never stored)."""

    download_url: str
    expires_in: int  # seconds


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    items: list[DocumentResponse]
    total: int
    page: int
    size: int
    pages: int
