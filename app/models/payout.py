# app/models/payout.py
"""
Payout model representing merchant withdrawal requests.

A payout is a merchant's request to withdraw funds from their platform
wallet to an external bank account.  Status lifecycle:
requested → processing → paid  (or: failed / cancelled)
"""

from sqlalchemy import (
    CHAR,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    CheckConstraint,
    func,
)

from app.db.base import BaseModel
from app.db.types import UUID, BIGINT


class Payout(BaseModel):
    __tablename__ = "payouts"

    merchant_id = Column(
        UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    amount = Column(BIGINT, nullable=False)          # minor units
    currency = Column(CHAR(3), nullable=False, default="NGN")
    status = Column(String(50), nullable=False, default="requested")
    # Human-readable reference, e.g. "PAYOUT-20261005-8a3f"
    reference = Column(String(100), nullable=False, unique=True, index=True)
    bank_account_last4 = Column(String(10), nullable=True)
    bank_name = Column(String(255), nullable=True)

    requested_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    paid_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_payouts_merchant", merchant_id),
        Index("idx_payouts_status", status),
        CheckConstraint("amount >= 0", name="ck_payouts_amount_non_negative"),
    )

    def __repr__(self):
        return f"<Payout(id={self.id}, merchant_id={self.merchant_id}, amount={self.amount}, status={self.status})>"