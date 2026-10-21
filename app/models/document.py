# app/models/document.py
"""
Document model — the single unified table for all S3-backed file storage.

Every file uploaded through the presigned-POST flow gets a row here, whether
it's a KYC identity document, a product image, a store logo, or a user avatar.
Domain linking is handled via the ``purpose`` + ``related_type``/``related_id``
columns, and the ``public`` flag gates whether a public CDN URL is returned.
"""

from enum import Enum as PyEnum

from sqlalchemy import Boolean, Column, Integer, String, Text, Index
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.db.types import UUID
from app.models.enums import DocumentPurpose, DocumentStatus


class Document(BaseModel):
    """Unified document record pointing at an S3 object."""

    __tablename__ = "documents"

    # --- Core reference -------------------------------------------------
    purpose = Column(
        String(64), nullable=False,
        comment="What kind of document this is (kyc, product_image, …)",
    )
    merchant_id = Column(
        UUID(as_uuid=True), nullable=True, index=True,
        comment="Owning merchant (NULL for user-scoped or platform docs).",
    )

    # --- File metadata -------------------------------------------------
    filename = Column(Text, nullable=False, comment="Original filename supplied by the client.")
    content_type = Column(Text, nullable=False, comment="MIME type declared at upload.")
    size_bytes = Column(Integer, nullable=False, comment="File size in bytes, checked at completion.")
    object_key = Column(Text, nullable=False, unique=True, comment="S3 object key.")

    # --- Lifecycle ------------------------------------------------------
    status = Column(
        String(32), nullable=False,
        default=DocumentStatus.PENDING.value,
        comment="pending → complete → cleanup",
    )
    public = Column(
        Boolean, nullable=False, default=False,
        comment="If True, served via public CDN URL; else presigned download.",
    )
    deleted_at = Column(Text, nullable=True, comment="Soft-delete timestamp (UTC ISO).")

    # --- Domain linking ------------------------------------------------
    # Allows arbitrary FK linkage without adding FK columns to every table.
    # ``related_type`` = "Product", "Merchant", "Store", "User", etc.
    related_type = Column(String(64), nullable=True, index=True)
    related_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # --- Indexes --------------------------------------------------------
    __table_args__ = (
        Index("idx_documents_merchant_purpose", "merchant_id", "purpose"),
        Index("idx_documents_related", "related_type", "related_id"),
        Index("idx_documents_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Document(id={self.id}, purpose={self.purpose}, "
            f"status={self.status}, key={self.object_key[:32]}…)>"
        )
