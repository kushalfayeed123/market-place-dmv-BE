# app/schemas/ledger.py
"""
Pydantic schemas for ledger requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum


class LedgerEntryType(PyEnum):
    SALE = "sale"
    COMMISSION = "commission"
    PAYOUT_HOLD = "payout_hold"
    PAYOUT_RELEASE = "payout_release"
    PAYOUT_PAID = "payout_paid"
    REFUND = "refund"
    ADJUSTMENT = "adjustment"


class LedgerDirection(PyEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class LedgerAccountType(PyEnum):
    PLATFORM_REVENUE = "platform_revenue"
    MERCHANT_WALLET = "merchant_wallet"
    PAYMENT_GATEWAY_CLEARING = "payment_gateway_clearing"
    REFUND_CLEARING = "refund_clearing"


class LedgerEntryResponse(BaseModel):
    id: str
    entry_group_id: str
    account_type: str
    merchant_id: Optional[str] = None
    direction: str
    entry_type: str
    amount: int  # Minor units
    currency: str
    order_id: Optional[str] = None
    payment_transaction_id: Optional[str] = None
    supersedes_entry_id: Optional[str] = None
    metadata: dict
    created_at: datetime
    created_by: str


class LedgerBalanceResponse(BaseModel):
    merchant_id: str
    currency: str
    total_balance: int  # Minor units - sum of all eligible credits minus debits
    available_balance: int  # Minor units - funds available for payout
    held_balance: int  # Minor units - funds currently held (e.g., awaiting delivery)
    calculated_at: datetime