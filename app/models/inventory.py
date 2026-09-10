# app/models/inventory.py
"""
Inventory model tracking stock levels for product variants.
"""

from sqlalchemy import Column, Integer, ForeignKey, Index, CheckConstraint
from app.db.types import UUID

from app.db.base import BaseModel


class Inventory(BaseModel):
    __tablename__ = "inventory"

    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False, unique=True)
    quantity_available = Column(Integer, nullable=False, default=0)
    quantity_reserved = Column(Integer, nullable=False, default=0)

    # Indexes and constraints
    __table_args__ = (
        Index('idx_inventory_variant', variant_id),
        CheckConstraint("quantity_available >= 0 AND quantity_reserved >= 0", name='ck_inventory_non_negative'),
    )

    def __repr__(self):
        return f"<Inventory(id={self.id}, variant_id={self.variant_id}, available={self.quantity_available}, reserved={self.quantity_reserved})>"
