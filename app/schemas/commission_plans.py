# app/schemas/commission_plans.py
"""
Pydantic schemas for commission plan requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CommissionPlanCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Name of the commission plan")
    percentage_bps: int = Field(..., ge=0, le=10000, description="Commission rate in basis points (e.g., 1000 = 10.00%)")
    flat_fee_minor: int = Field(default=0, ge=0, description="Flat fee in minor units (e.g., kobo for NGN)")
    currency: str = Field(default="NGN", min_length=3, max_length=3, description="Currency code (ISO 4217)")
    is_default: bool = Field(default=False, description="Whether this is the default commission plan")


class CommissionPlanResponse(BaseModel):
    id: str
    name: str
    percentage_bps: int
    flat_fee_minor: int
    currency: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
