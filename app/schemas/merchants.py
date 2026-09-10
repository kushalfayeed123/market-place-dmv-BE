# app/schemas/merchants.py
"""
Pydantic schemas for merchants requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum as PyEnum


class KycStatus(PyEnum):
    PENDING = "pending"
    TEST_MODE = "test_mode"
    VERIFIED = "verified"
    REJECTED = "rejected"


class MerchantCreate(BaseModel):
    owner_user_id: str
    business_name: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    kyc_status: Optional[KycStatus] = None
    kyc_provider_ref: Optional[str] = None
    commission_plan_id: str

    # Merchant address fields
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None  # ISO 3166-1 alpha-2


class MerchantUpdate(BaseModel):
    """Partial-update schema for PUT /{merchant_id}."""

    business_name: Optional[str] = Field(default=None, min_length=1)
    slug: Optional[str] = Field(default=None, min_length=1)
    kyc_status: Optional[KycStatus] = None
    kyc_provider_ref: Optional[str] = None

    # Merchant address fields
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class MerchantResponse(BaseModel):
    id: str
    owner_user_id: str
    business_name: str
    slug: str
    kyc_status: str
    kyc_provider_ref: Optional[str] = None
    commission_plan_id: str

    # Merchant address fields
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MerchantPayoutAccountCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=50)
    currency: str = Field(..., min_length=3, max_length=3)
    external_ref: str = Field(..., min_length=1)
    account_last4: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    bank_code: Optional[str] = None
    routing_number: Optional[str] = None
    account_type: Optional[str] = None
    country: Optional[str] = None  # ISO 3166-1 alpha-2


class MerchantPayoutAccountUpdate(BaseModel):
    """Partial-update schema for payout account."""

    account_last4: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    bank_code: Optional[str] = None
    routing_number: Optional[str] = None
    account_type: Optional[str] = None
    country: Optional[str] = None
    is_active: Optional[bool] = None


class MerchantPayoutAccountResponse(BaseModel):
    id: str
    merchant_id: str
    provider: str
    currency: str
    external_ref: str
    account_last4: Optional[str] = None
    bank_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    bank_code: Optional[str] = None
    routing_number: Optional[str] = None
    account_type: Optional[str] = None
    country: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}