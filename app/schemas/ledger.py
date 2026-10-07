# app/schemas/ledger.py
"""
Pydantic schemas for ledger requests and responses.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime, timezone
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

    @field_validator("calculated_at", mode="before")
    @classmethod
    def coerce_calculated_at(cls, v):
        """Ensure calculated_at is always a valid datetime.

        Handles edge cases where a SQLAlchemy expression or other non-datetime
        value might be passed (e.g., from stale code or caching), preventing
        422 validation errors in production.
        """
        if isinstance(v, datetime):
            return v
        # If a string is passed, try to parse it as ISO 8601
        if isinstance(v, str):
            try:
                return datetime.fromisoformat(v)
            except (ValueError, TypeError):
                pass
        # Fallback: use current UTC time
        return datetime.now(timezone.utc)
