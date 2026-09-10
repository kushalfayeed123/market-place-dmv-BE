# app/models/ledger_entry.py
"""
Ledger entry model representing the immutable financial ledger.
This is the system of record for every unit of money that moves in the platform.
"""

from sqlalchemy import Column, Integer, BigInteger, DateTime, ForeignKey, Index, CheckConstraint, String, Text, text
from app.db.types import UUID, BIGINT, CHAR
from enum import Enum as PyEnum

from app.db.base import BaseModel


class LedgerAccountType(PyEnum):
    PLATFORM_REVENUE = "platform_revenue"
    MERCHANT_WALLET = "merchant_wallet"
    PAYMENT_GATEWAY_CLEARING = "payment_gateway_clearing"
    REFUND_CLEARING = "refund_clearing"


class LedgerDirection(PyEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerEntryType(PyEnum):
    SALE = "sale"
    COMMISSION = "commission"
    PAYOUT_HOLD = "payout_hold"
    PAYOUT_RELEASE = "payout_release"
    PAYOUT_PAID = "payout_paid"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class LedgerEntry(BaseModel):
    __tablename__ = "ledger_entries"

    # Intentional override: BigInteger auto-increment PK for ledger (not UUID from BaseModel)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    entry_group_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    account_type = Column(String(50), nullable=False)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=True, index=True)
    direction = Column(String(20), nullable=False)
    entry_type = Column(String(50), nullable=False)
    amount = Column(BigInteger, nullable=False)  # Minor units; sign comes from direction
    currency = Column(CHAR(3), nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True, index=True)
    payment_transaction_id = Column(UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=True, index=True)
    supersedes_entry_id = Column(BigInteger, ForeignKey("ledger_entries.id"), nullable=True, index=True)
    ledger_metadata = Column(Text, nullable=False, server_default=text("('{}')"))  # JSONB equivalent
    created_by = Column(Text, nullable=False, server_default=text("('system')"))

    # Indexes and constraints
    __table_args__ = (
        Index('idx_ledger_merchant', merchant_id, currency),
        Index('idx_ledger_order', order_id),
        Index('idx_ledger_group', entry_group_id),
        Index('idx_ledger_supersedes', supersedes_entry_id),
        CheckConstraint("amount > 0", name='ck_ledger_entries_amount_positive'),
    )

    def __repr__(self):
        return f"<LedgerEntry(id={self.id}, entry_group_id={self.entry_group_id}, account_type={self.account_type}, direction={self.direction}, entry_type={self.entry_type}, amount={self.amount}, ledger_metadata={self.ledger_metadata})>"
