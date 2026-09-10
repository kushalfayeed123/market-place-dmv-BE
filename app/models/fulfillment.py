# app/models/fulfillment.py
"""
Fulfillment model representing shipment or digital delivery of orders.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from app.db.types import UUID
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.models.enums import FulfillmentKindOrder, FulfillmentStatus


class Fulfillment(BaseModel):
    __tablename__ = "fulfillments"

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    type = Column(String(50), nullable=False)  # Using String instead of Enum for flexibility
    status = Column(String(50), nullable=False, default=FulfillmentStatus.PENDING.value)
    carrier = Column(Text, nullable=True)
    # VARCHAR(255): indexed column, MySQL cannot index TEXT without a prefix length
    tracking_number = Column(String(255), nullable=True)
    download_token = Column(Text, nullable=True)  # For digital deliveries
    downloads_used = Column(Integer, nullable=False, default=0)
    delivered_at = Column(DateTime(timezone=True), nullable=True)
    dispute_window_ends = Column(DateTime(timezone=True), nullable=True)  # delivered_at + N days

    # Indexes
    __table_args__ = (
        Index('idx_fulfillments_order', order_id),
        Index('idx_fulfillments_merchant', merchant_id),
        Index('idx_fulfillments_status', status),
        Index('idx_fulfillments_tracking', tracking_number),
    )

    def __repr__(self):
        return f"<Fulfillment(id={self.id}, order_id={self.order_id}, type={self.type}, status={self.status})>"
