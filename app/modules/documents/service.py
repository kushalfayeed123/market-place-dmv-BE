# app/modules/documents/service.py
"""
Document service — document lifecycle, validation, domain linking, and cleanup.

All S3 I/O is delegated to :mod:`app.core.storage` and wrapped in
``run_in_threadpool`` because boto3 is synchronous while this service runs
in an async context.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.security import to_uuid
from app.core.storage import (
    build_key,
    delete_object,
    inspect_object,
    presign_download,
    presign_upload,
    public_url_for,
    guess_content_type,
    read_object_head,
    signature_matches,
    upload_file_from_bytes,
)
from app.models.document import Document
from app.models.enums import DocumentPurpose, DocumentStatus
from app.schemas.document import (
    DocumentCompleteRequest,
    DocumentListResponse,
    DocumentResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

PUBLIC_PURPOSES: frozenset[str] = frozenset({
    DocumentPurpose.PRODUCT_IMAGE.value,
    DocumentPurpose.STORE_LOGO.value,
    DocumentPurpose.STORE_BANNER.value,
    DocumentPurpose.USER_AVATAR.value,
})

ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    DocumentPurpose.KYC.value: {"application/pdf", "image/jpeg", "image/png"},
    DocumentPurpose.PRODUCT_IMAGE.value: {"image/jpeg", "image/png", "image/webp", "image/gif"},
    DocumentPurpose.STORE_LOGO.value: {"image/jpeg", "image/png", "image/webp", "image/svg+xml"},
    DocumentPurpose.STORE_BANNER.value: {"image/jpeg", "image/png", "image/webp", "image/gif"},
    DocumentPurpose.USER_AVATAR.value: {"image/jpeg", "image/png", "image/webp", "image/gif"},
}

MAGIC_SIGNATURES: dict[str, bytes] = {
    "application/pdf": b"%PDF-",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/gif": b"GIF87a",
    "image/webp": b"RIFF",
    "image/svg+xml": b"<?xml",
}

PURPOSE_TARGETS: dict[str, tuple[str, str]] = {
    DocumentPurpose.KYC.value: ("Merchant", "kyc_document_id"),
    DocumentPurpose.PRODUCT_IMAGE.value: ("Product", "urls"),
    DocumentPurpose.STORE_LOGO.value: ("Store", "logo_document_id"),
    DocumentPurpose.STORE_BANNER.value: ("Store", "banner_document_id"),
    DocumentPurpose.USER_AVATAR.value: ("User", "avatar_url"),
}


def to_uuid_safe(value: str | None):
    """Best-effort UUID conversion, returning None on failure."""
    if not value:
        return None
    try:
        return to_uuid(value)
    except (ValueError, TypeError):
        return None


def _check_magic(content_type: str, head: bytes) -> bool:
    """
    Verify that *head* starts with the expected magic signature for *content_type*.

    Returns ``True`` if the content type is unknown (can't validate) or the
    signature matches; returns ``False`` otherwise.
    """
    expected = MAGIC_SIGNATURES.get(content_type)
    if expected is None:
        return True
    return head[: len(expected)] == expected


def _to_response(doc: Document) -> DocumentResponse:
    """Convert a Document model instance to a DocumentResponse schema."""
    return DocumentResponse(
        id=str(doc.id),
        purpose=doc.purpose,
        merchant_id=str(doc.merchant_id) if doc.merchant_id else None,
        filename=doc.filename,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        object_key=doc.object_key,
        status=doc.status,
        public=doc.public,
        related_type=doc.related_type,
        related_id=str(doc.related_id) if doc.related_id else None,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


class DocumentService:
    """Service layer encapsulating document lifecycle and domain linking."""

    def __init__(self, db: AsyncSession):
        self._db = db

    # ── Presigned upload ──────────────────────────────────────────────

    async def create_presigned_upload(
        self,
        merchant_id_str: str,
        payload: DocumentUploadRequest,
    ) -> DocumentUploadResponse:
        """
        Validate the request, create a ``PENDING`` document row, and return
        S3 presigned POST fields the browser should POST the actual file to.
        """
        merchant_id = to_uuid(merchant_id_str)

        # Validate purpose
        if payload.purpose not in {p.value for p in DocumentPurpose}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid document purpose: {payload.purpose}",
            )

        # Validate content type
        allowed = ALLOWED_CONTENT_TYPES.get(payload.purpose, set())
        if allowed and payload.content_type not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Content type '{payload.content_type}' is not allowed "
                    f"for purpose '{payload.purpose}'. "
                    f"Allowed: {sorted(allowed)}"
                ),
            )

        # Validate size
        max_bytes = settings.S3_MAX_UPLOAD_MB * 1024 * 1024
        if payload.size_bytes > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File exceeds max upload size of {settings.S3_MAX_UPLOAD_MB}MB",
            )
        if payload.size_bytes <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size must be greater than zero",
            )

        # Validate related_type / related_id if provided
        if payload.related_type or payload.related_id:
            await self._validate_domain_link(payload, merchant_id)

        # Build S3 key
        key = build_key(
            merchant_id=str(merchant_id),
            purpose=payload.purpose,
            original_filename=payload.filename,
        )

        # Create document row (PENDING status)
        doc = Document(
            purpose=payload.purpose,
            merchant_id=merchant_id,
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
            object_key=key,
            status=DocumentStatus.PENDING.value,
            public=payload.purpose in PUBLIC_PURPOSES,
            related_type=payload.related_type,
            related_id=to_uuid(payload.related_id) if payload.related_id else None,
        )
        self._db.add(doc)
        await self._db.commit()
        await self._db.refresh(doc)

        # Generate presigned POST via threadpool (boto3 is sync)
        presigned = await run_in_threadpool(
            presign_upload,
            bucket=settings.S3_BUCKET,
            key=key,
            content_type=payload.content_type,
            max_bytes=max_bytes,
            ttl_seconds=settings.S3_UPLOAD_URL_TTL_SECONDS,
        )

        return DocumentUploadResponse(
            document_id=str(doc.id),
            upload_url=presigned["url"],
            upload_fields=presigned["fields"],
            key=key,
            max_size_bytes=max_bytes,
            ttl_seconds=settings.S3_UPLOAD_URL_TTL_SECONDS,
        )

    # ── Complete upload ─────────────────────────────────────────────────

    async def complete_upload(
        self, request: DocumentCompleteRequest,
    ) -> DocumentResponse:
        """
        Mark a document as ``COMPLETE``.  Idempotent — calling complete on
        an already-complete document returns the existing record.
        """
        result = await self._db.execute(
            select(Document).where(Document.object_key == request.key)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        # Idempotency: if already complete, return as-is.
        if doc.status == DocumentStatus.COMPLETE.value:
            return _to_response(doc)

        # Verify object actually exists in S3
        meta = await run_in_threadpool(
            inspect_object,
            bucket=settings.S3_BUCKET,
            key=request.key,
        )
        if meta is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uploaded file not found in storage",
            )

        # Verify size matches
        content_length = meta.get("ContentLength", 0)
        if content_length != doc.size_bytes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Size mismatch: S3 reports {content_length} bytes, "
                    f"expected {doc.size_bytes}"
                ),
            )

        # Verify checksum if the client sent one
        if request.checksum:
            etag = meta.get("ETag", "").strip('"')
            if not signature_matches(request.checksum, etag):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Checksum mismatch — file may be corrupted",
                )

        # Verify magic bytes match the declared content type
        head = await run_in_threadpool(
            read_object_head,
            bucket=settings.S3_BUCKET,
            key=request.key,
        )
        if head is not None and not _check_magic(doc.content_type, head):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"File content does not match declared content type "
                    f"'{doc.content_type}' — possible spoofing"
                ),
            )

        # Link to domain model
        await self._link_to_domain(doc)

        # Finalize
        doc.status = DocumentStatus.COMPLETE.value
        await self._db.commit()
        await self._db.refresh(doc)
        return _to_response(doc)

    # ── Domain linking ──────────────────────────────────────────────────

    async def _validate_domain_link(
        self, payload: DocumentUploadRequest, merchant_id
    ) -> None:
        """Validate that ``related_type`` matches the purpose's target."""
        target_info = PURPOSE_TARGETS.get(payload.purpose)
        if target_info and payload.related_type:
            expected_type = target_info[0]
            if payload.related_type != expected_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"purpose '{payload.purpose}' expects related_type "
                        f"'{expected_type}', got '{payload.related_type}'"
                    ),
                )

    async def _link_to_domain(self, doc: Document) -> None:
        """Sync the domain model so its URL / FK column points to this document."""
        if not doc.related_type or not doc.related_id:
            return

        related_uuid = (
            doc.related_id if isinstance(doc.related_id, str)
            else doc.related_id
        )

        if doc.related_type == "Product":
            from app.models.product import Product

            result = await self._db.execute(
                select(Product).where(Product.id == related_uuid)
            )
            product = result.scalar_one_or_none()
            if product is None:
                return
            urls = product.urls
            if isinstance(urls, str):
                try:
                    urls = json.loads(urls)
                except (json.JSONDecodeError, TypeError):
                    urls = []
            if not isinstance(urls, list):
                urls = []
            url = public_url_for(doc.object_key) if doc.public else None
            if url and url not in urls:
                urls.append(url)
            product.urls = json.dumps(urls)

        elif doc.related_type in ("Merchant", "Store"):
            model_cls = self._resolve_model(doc.related_type)
            if model_cls is None:
                return
            result = await self._db.execute(
                select(model_cls).where(model_cls.id == related_uuid)
            )
            obj = result.scalar_one_or_none()
            if obj is None:
                return
            field_name = PURPOSE_TARGETS[doc.purpose][1]
            setattr(obj, field_name, related_uuid)

    def _resolve_model(self, related_type: str) -> type | None:
        """Map a related_type string to its SQLAlchemy model class."""
        from app.models.merchant import Merchant
        from app.models.store import Store
        from app.models.user import User

        return {
            "Merchant": Merchant,
            "Store": Store,
            "User": User,
        }.get(related_type)

    # ── Listing & retrieval ───────────────────────────────────────────

    async def list_documents(
        self,
        merchant_id_str: str | None = None,
        purpose: str | None = None,
        related_type: str | None = None,
        related_id: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> DocumentListResponse:
        """List documents, optionally filtered by merchant / purpose / relation."""
        stmt = (
            select(Document)
            .where(Document.deleted_at.is_(None))
            .order_by(Document.created_at.desc())
        )
        if merchant_id_str:
            mid = to_uuid_safe(merchant_id_str)
            if mid:
                stmt = stmt.where(Document.merchant_id == mid)
        if purpose:
            stmt = stmt.where(Document.purpose == purpose)
        if related_type:
            stmt = stmt.where(Document.related_type == related_type)
        if related_id:
            rid = to_uuid_safe(related_id)
            if rid:
                stmt = stmt.where(Document.related_id == rid)

        # Count total
        count_result = await self._db.execute(
            select(func.count()).select_from(stmt.subquery())
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            stmt.offset(skip).limit(max(1, min(limit, 200)))
        )
        docs = result.scalars().all()

        items = [_to_response(d) for d in docs]
        pages = (total + limit - 1) // limit if limit else 0
        return DocumentListResponse(
            items=items,
            total=total,
            page=skip // max(limit, 1) + 1,
            size=len(items),
            pages=pages,
        )

    async def get_document(
        self,
        merchant_id_str: str | None,
        doc_id: str,
    ) -> DocumentResponse:
        """Fetch a single document by id, scoped to the merchant for auth."""
        doc_uuid = to_uuid(doc_id)
        stmt = select(Document).where(
            Document.id == doc_uuid,
            Document.deleted_at.is_(None),
        )
        # Scope by merchant unless admin (router passes None for admin scope).
        if merchant_id_str:
            mid = to_uuid_safe(merchant_id_str)
            if mid:
                stmt = stmt.where(Document.merchant_id == mid)

        result = await self._db.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc is None:
            # 404 (not 403) to prevent existence disclosure
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )
        return _to_response(doc)

    async def get_download_url(
        self,
        merchant_id_str: str | None,
        doc_id: str,
    ) -> tuple[str, int]:
        """
        Generate a short-lived presigned download URL.

        For public documents (CDN-backed), the public URL is returned
        directly (expires_in = 0).
        """
        doc_resp = await self.get_document(merchant_id_str, doc_id)

        if doc_resp.public and settings.S3_PUBLIC_BASE_URL:
            return public_url_for(doc_resp.object_key), 0

        url = await run_in_threadpool(
            presign_download,
            bucket=settings.S3_BUCKET,
            key=doc_resp.object_key,
            ttl_seconds=settings.S3_DOWNLOAD_URL_TTL_SECONDS,
        )
        return url, settings.S3_DOWNLOAD_URL_TTL_SECONDS

    async def delete_document(
        self,
        merchant_id_str: str | None,
        doc_id: str,
    ) -> bool:
        """Soft-delete a document.  Queues S3 deletion as a side-effect."""
        doc_uuid = to_uuid(doc_id)
        stmt = select(Document).where(
            Document.id == doc_uuid,
            Document.deleted_at.is_(None),
        )
        if merchant_id_str:
            mid = to_uuid_safe(merchant_id_str)
            if mid:
                stmt = stmt.where(Document.merchant_id == mid)

        result = await self._db.execute(stmt)
        doc = result.scalar_one_or_none()
        if doc is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        doc.deleted_at = datetime.now(timezone.utc).isoformat()
        doc.status = DocumentStatus.CLEANUP.value
        await self._db.commit()

        # Delete from S3 (non-blocking via threadpool).
        await run_in_threadpool(
            delete_object,
            bucket=settings.S3_BUCKET,
            key=doc.object_key,
        )
        return True

    async def cleanup_stale_documents(self, older_than_hours: int = 24) -> int:
        """
        Remove documents stuck in ``PENDING`` or ``CLEANUP`` for longer than
        *older_than_hours*, including the corresponding S3 objects.
        Returns the count of hard-deleted rows.
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)

        stale = await self._db.execute(
            select(Document).where(
                Document.status.in_([
                    DocumentStatus.PENDING.value,
                    DocumentStatus.CLEANUP.value,
                ]),
                Document.created_at < cutoff,
            )
        )
        docs = stale.scalars().all()

        deleted = 0
        for doc in docs:
            await run_in_threadpool(
                delete_object,
                bucket=settings.S3_BUCKET,
                key=doc.object_key,
            )
            await self._db.delete(doc)
            deleted += 1

        if deleted:
            await self._db.commit()
        return deleted

    async def migrate_product_image(
        self,
        product_id_str: str,
        file_data: bytes,
        original_filename: str,
    ) -> str:
        """
        Upload a byte blob to S3 and return the public CDN URL.
        Used by the migration script for existing local product images.
        """
        merchant_id = await self._get_product_merchant(product_id_str)
        key = build_key(
            merchant_id=str(merchant_id),
            purpose=DocumentPurpose.PRODUCT_IMAGE.value,
            original_filename=original_filename,
        )
        content_type = guess_content_type(original_filename)
        await run_in_threadpool(
            upload_file_from_bytes,
            bucket=settings.S3_BUCKET,
            key=key,
            data=file_data,
            content_type=content_type,
        )
        return public_url_for(key)

    async def _get_product_merchant(self, product_id_str: str):
        """Look up the merchant_id for a product (used during migration)."""
        from app.models.product import Product

        pid = to_uuid(product_id_str)
        result = await self._db.execute(
            select(Product).where(Product.id == pid)
        )
        product = result.scalar_one_or_none()
        if product is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Product {product_id_str} not found",
            )
        return product.merchant_id


