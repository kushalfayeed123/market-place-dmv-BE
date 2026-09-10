# app/models/product_variant.py
"""
Product variant model representing different versions of a product (e.g., size, color).
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, text
from app.db.types import UUID, BIGINT, CHAR
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.models.enums import InventoryPolicy


class ProductVariant(BaseModel):
    __tablename__ = "product_variants"

    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    # VARCHAR(255): unique + indexed column, MySQL cannot index TEXT without a prefix length
    sku = Column(String(255), nullable=False, unique=True)
    attributes = Column(Text, nullable=False, server_default=text("('{}')"))  # JSONB equivalent
    price_override_amount = Column(BIGINT, nullable=True)
    price_override_currency = Column(CHAR(3), nullable=True)
    inventory_policy = Column(String(50), nullable=False, default=InventoryPolicy.TRACKED.value)

    # Indexes
    __table_args__ = (
        Index('idx_product_variants_product', product_id),
        Index('idx_product_variants_sku', sku),
    )

    def __repr__(self):
        return f"<ProductVariant(id={self.id}, sku={self.sku}, product_id={self.product_id})>"
