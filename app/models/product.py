# app/models/product.py
"""
Product model representing items sold in the marketplace.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, CheckConstraint, UniqueConstraint, text
from app.db.types import UUID, BIGINT, CHAR
from sqlalchemy.sql import func
from enum import Enum as PyEnum

from app.db.base import BaseModel
from app.models.enums import InventoryPolicy


class FulfillmentKind(PyEnum):
    PHYSICAL = "physical"
    DIGITAL = "digital"
    SERVICE = "service"


class ProductStatus(PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Product(BaseModel):
    __tablename__ = "products"

    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    store_id = Column(UUID(as_uuid=True), ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)
    title = Column(Text, nullable=False)
    # VARCHAR(255): indexed + unique column, MySQL cannot index TEXT without a prefix length
    slug = Column(String(255), nullable=False)
    description = Column(Text)
    fulfillment_type = Column(String(50), nullable=False)  # Using String instead of Enum for flexibility
    status = Column(String(50), nullable=False, default=ProductStatus.DRAFT.value)
    base_price_amount = Column(BIGINT, nullable=False)  # Minor units (kobo)
    base_price_currency = Column(CHAR(3), nullable=False, default="NGN")
    attributes = Column(Text, nullable=False, server_default=text("('{}')"))  # JSONB equivalent

    # Indexes and constraints
    __table_args__ = (
        Index('idx_products_merchant', merchant_id),
        Index('idx_products_store', store_id),
        Index('idx_products_status', status, postgresql_where=(status == ProductStatus.ACTIVE.value)),
        Index('idx_products_slug', slug),
        UniqueConstraint('store_id', 'slug', name='uq_products_store_slug'),
        CheckConstraint("base_price_amount >= 0", name='ck_products_base_price_non_negative'),
    )

    def __repr__(self):
        return f"<Product(id={self.id}, title={self.title}, merchant_id={self.merchant_id}, status={self.status})>"
