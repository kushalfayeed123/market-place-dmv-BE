# app/models/order.py
"""
Order model representing customer purchases.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint, CheckConstraint, text
from app.db.types import UUID, BIGINT, CHAR
from sqlalchemy.sql import func
from enum import Enum as PyEnum

from app.db.base import BaseModel
from app.models.enums import FulfillmentKindOrder, FulfillmentStatus


class OrderStatus(PyEnum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_FULFILLED = "partially_fulfilled"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    AWAITING_APPROVAL = "awaiting_approval"


class Order(BaseModel):
    __tablename__ = "orders"

    buyer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Human-readable order number, e.g. "ORD-20261005-8a3f". Unique and
    # customer-facing (used in confirmation emails + UI).
    order_number = Column(String(50), nullable=False, unique=True, index=True)
    status = Column(String(50), nullable=False, default=OrderStatus.PENDING.value)
    currency = Column(CHAR(3), nullable=False)
    total_amount = Column(BIGINT, nullable=False)  # Minor units
    # VARCHAR(255): unique column, MySQL cannot index TEXT without a prefix length
    idempotency_key = Column(String(255), nullable=True, unique=True)

    # Indexes and constraints
    __table_args__ = (
        Index('idx_orders_buyer', buyer_id),
        Index('idx_orders_status', status),
        Index('idx_orders_created_at', text('created_at DESC')),
        UniqueConstraint('idempotency_key', name='uq_orders_idempotency_key'),
        CheckConstraint("total_amount >= 0", name='ck_orders_total_non_negative'),
    )

    def __repr__(self):
        return f"<Order(id={self.id}, order_number={self.order_number}, buyer_id={self.buyer_id}, status={self.status}, total={self.total_amount})>"
