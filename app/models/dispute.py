# app/models/dispute.py
"""
Dispute model representing customer-initiated chargebacks or order disputes.

Status lifecycle: open → evidence_submitted → won | lost
"""

from sqlalchemy import (
    BIGINT,
    CHAR,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    CheckConstraint,
)

from app.db.base import BaseModel
from app.db.types import UUID


class Dispute(BaseModel):
    __tablename__ = "disputes"

    merchant_id = Column(
        UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    order_number = Column(String(50), nullable=False, index=True)
    reason = Column(Text, nullable=False)
    amount = Column(BIGINT, nullable=False)          # minor units
    currency = Column(CHAR(3), nullable=False, default="NGN")
    respond_by = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(50), nullable=False, default="open")

    __table_args__ = (
        Index("idx_disputes_merchant", merchant_id),
        Index("idx_disputes_status", status),
        CheckConstraint("amount >= 0", name="ck_disputes_amount_non_negative"),
    )

    def __repr__(self):
        return f"<Dispute(id={self.id}, order_number={self.order_number}, status={self.status})>"