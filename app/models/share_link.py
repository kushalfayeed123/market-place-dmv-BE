# app/models/share_link.py
"""
Share link model — a merchant-generated public link to a store or a set of products.

A store link (``store_id`` set, no product rows) shows every active product in the
store. A product link carries one row per embedded product; visitors see a listing
of just those products. The normal cart/checkout flow is unchanged.
"""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Table, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.db.types import UUID

# Association table: share link -> embedded products.
share_link_products = Table(
    "share_link_products",
    BaseModel.metadata,
    Column(
        "link_id",
        UUID(as_uuid=True),
        ForeignKey("share_links.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "product_id",
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Index("idx_share_link_products_product", "product_id"),
)


class ShareLink(BaseModel):
    __tablename__ = "share_links"

    # Short, URL-safe, unguessable code used in the public link path (/s/{code}).
    code = Column(String(32), nullable=False, unique=True)
    merchant_id = Column(
        UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False
    )
    store_id = Column(
        UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False
    )
    # Optional human-friendly label, e.g. "Summer picks".
    title = Column(String(255), nullable=True)
    # JSON-encoded list of product ids for product-set links; empty for a store link.
    product_ids = Column(Text, nullable=False, server_default="[]")
    is_active = Column(String(8), nullable=False, server_default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_share_links_merchant", merchant_id),
        Index("idx_share_links_store", store_id),
        UniqueConstraint("code", name="uq_share_links_code"),
    )

    def __repr__(self):
        return f"<ShareLink(id={self.id}, code={self.code}, store_id={self.store_id})>"
