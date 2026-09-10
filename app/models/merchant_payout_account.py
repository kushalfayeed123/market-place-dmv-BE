# app/models/merchant_payout_account.py
"""
Merchant payout account model for storing payment provider account details.

Sensitive fields (e.g. full bank account numbers) are NOT stored in plaintext.
Only non-reversible identifiers — ``external_ref`` (provider-side account ID),
``account_last4``, and ``bank_name`` — are persisted.  Any full account number
must be encrypted at the application layer before being written here.
"""

from sqlalchemy import (
    CHAR,
    Boolean,
    Column,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import BaseModel
from app.db.types import UUID


class MerchantPayoutAccount(BaseModel):
    __tablename__ = "merchant_payout_accounts"

    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    # VARCHAR(50): indexed + unique column, MySQL cannot index TEXT without a prefix length
    provider = Column(String(50), nullable=False)  # 'paystack', 'flutterwave', 'stripe', etc.
    currency = Column(CHAR(3), nullable=False)
    external_ref = Column(Text, nullable=False)  # e.g. Paystack subaccount_code
    account_last4 = Column(Text)
    bank_name = Column(Text)
    # Additional bank-account metadata
    account_holder_name = Column(Text, nullable=True)
    bank_code = Column(String(50), nullable=True)  # e.g. Nigerian bank routing code
    routing_number = Column(String(50), nullable=True)
    account_type = Column(String(20), nullable=True)  # 'checking', 'savings', etc.
    country = Column(CHAR(2), nullable=True)  # ISO 3166-1 alpha-2 of the bank account
    is_active = Column(Boolean, nullable=False, default=True)

    # Indexes and constraints
    __table_args__ = (
        Index('idx_merchant_payout_accounts_merchant', merchant_id),
        Index('idx_merchant_payout_accounts_provider', provider),
        Index('idx_merchant_payout_accounts_country', country),
        UniqueConstraint('merchant_id', 'provider', 'currency', name='uq_merchant_payout_account'),
    )

    def __repr__(self):
        return f"<MerchantPayoutAccount(id={self.id}, merchant_id={self.merchant_id}, provider={self.provider})>"