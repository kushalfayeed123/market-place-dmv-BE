# app/models/payment_transaction.py
"""
Payment transaction model for recording payments processed through providers.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint, CheckConstraint
from app.db.types import UUID, BIGINT, CHAR
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class PaymentTransaction(BaseModel):
    __tablename__ = "payment_transactions"
    
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    # VARCHAR(50)/VARCHAR(255): indexed/unique columns, MySQL cannot index TEXT without a prefix length
    provider = Column(String(50), nullable=False)  # e.g., 'paystack'
    provider_reference = Column(String(255), nullable=False)  # Provider's transaction reference
    status = Column(String(50), nullable=False)  # initialized | success | failed | refunded
    amount = Column(BIGINT, nullable=False)  # Minor units
    currency = Column(CHAR(3), nullable=False)
    raw_payload = Column(Text, nullable=True)  # JSONB equivalent
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_payment_transactions_order', order_id),
        Index('idx_payment_transactions_provider', provider),
        Index('idx_payment_transactions_status', status),
        UniqueConstraint('provider', 'provider_reference', name='uq_payment_transactions_provider_ref'),
        CheckConstraint("amount >= 0", name='ck_payment_transactions_amount_non_negative'),
    )
    
    def __repr__(self):
        return f"<PaymentTransaction(id={self.id}, order_id={self.order_id}, provider={self.provider}, status={self.status})>"