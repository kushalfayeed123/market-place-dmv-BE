# app/models/order_item.py
"""
Order item model representing individual products within an order.
"""

from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index, CheckConstraint
from app.db.types import UUID, BIGINT, CHAR
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class OrderItem(BaseModel):
    __tablename__ = "order_items"
    
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(BIGINT, nullable=False)  # Minor units
    currency = Column(CHAR(3), nullable=False)
    line_total = Column(BIGINT, nullable=False)  # quantity * unit_price
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_order_items_order', order_id),
        Index('idx_order_items_merchant', merchant_id),
        Index('idx_order_items_product', product_id),
        CheckConstraint("quantity > 0", name='ck_order_items_quantity_positive'),
        CheckConstraint("unit_price >= 0", name='ck_order_items_unit_price_non_negative'),
        CheckConstraint("line_total >= 0", name='ck_order_items_line_total_non_negative'),
    )
    
    def __repr__(self):
        return f"<OrderItem(id={self.id}, order_id={self.order_id}, product_id={self.product_id}, quantity={self.quantity})>"