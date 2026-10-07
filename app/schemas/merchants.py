# app/schemas/merchants.py
"""
Pydantic schemas for merchants requests and responses.
"""

from datetime import datetime
from enum import Enum as PyEnum

from pydantic import BaseModel, Field


class KycStatus(PyEnum):
    PENDING = "pending"
    TEST_MODE = "test_mode"
    VERIFIED = "verified"
    REJECTED = "rejected"


class MerchantCreate(BaseModel):
    owner_user_id: str
    business_name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    kyc_status: KycStatus | None = None
    kyc_provider_ref: str | None = None
    commission_plan_id: str

    # Merchant address fields
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2


class MerchantOnboard(BaseModel):
    business_name: str
    slug: str
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    country: str | None = Field(
        default=None, min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$"
    )


class MerchantUpdate(BaseModel):
    """Partial-update schema for PUT /{merchant_id}."""

    business_name: str | None = Field(default=None, min_length=1)
    slug: str | None = Field(default=None, min_length=1)
    kyc_status: KycStatus | None = None
    kyc_provider_ref: str | None = None

    # Merchant address fields
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None


class MerchantResponse(BaseModel):
    id: str
    owner_user_id: str
    business_name: str
    slug: str
    kyc_status: str
    kyc_provider_ref: str | None = None
    commission_plan_id: str

    # Merchant address fields
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    country: str | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MerchantPayoutAccountCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(..., min_length=3, max_length=3)
    external_ref: str = Field(..., min_length=1)
    account_last4: str | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None
    bank_code: str | None = None
    routing_number: str | None = None
    account_type: str | None = None
    country: str | None = None  # ISO 3166-1 alpha-2


class MerchantPayoutAccountUpdate(BaseModel):
    """Partial-update schema for payout account."""

    account_last4: str | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None
    bank_code: str | None = None
    routing_number: str | None = None
    account_type: str | None = None
    country: str | None = None
    is_active: bool | None = None


class MerchantPayoutAccountResponse(BaseModel):
    id: str
    merchant_id: str
    provider: str
    currency: str
    external_ref: str
    account_last4: str | None = None
    bank_name: str | None = None
    account_holder_name: str | None = None
    bank_code: str | None = None
    routing_number: str | None = None
    account_type: str | None = None
    country: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PayoutCreate(BaseModel):
    """Schema for requesting a payout (merchant withdrawal)."""

    amount: int = Field(..., gt=0, description="Amount in minor units (e.g. kobo)")
    currency: str = Field(default="NGN", min_length=3, max_length=3)
    bank_account_last4: str | None = None
    bank_name: str | None = None


class PayoutResponse(BaseModel):
    """Response schema for a payout request."""

    id: str
    merchant_id: str
    amount: int  # Minor units
    currency: str
    status: str
    reference: str
    bank_account_last4: str | None = None
    bank_name: str | None = None
    requested_at: datetime | None = None
    processed_at: datetime | None = None
    paid_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KycReviewRequest(BaseModel):
    """Schema for admin KYC review."""

    kyc_status: str = Field(..., pattern="^(pending|test_mode|verified|rejected)$")
    reason: str | None = None
