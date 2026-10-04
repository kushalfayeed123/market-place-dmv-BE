# app/schemas/catalog.py
"""
Pydantic schemas for catalog requests and responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1)
    parent_id: str | None = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ProductCreate(BaseModel):
    merchant_id: str
    store_id: str
    category_id: str | None = None
    title: str = Field(..., min_length=1)
    slug: str = Field(..., min_length=1)
    description: str | None = None
    fulfillment_type: str = Field(..., pattern="^(physical|digital|service)$")
    status: str | None = Field(None, pattern="^(draft|active|suspended)$")
    base_price_amount: int = Field(..., ge=0)  # Minor units
    base_price_currency: str = Field(default="NGN", min_length=3, max_length=3)
    attributes: dict[str, Any] | None = {}
    urls: list[str] | None = None


class ProductResponse(BaseModel):
    id: str
    merchant_id: str
    store_id: str
    store_name: str | None = None
    category_id: str | None = None
    title: str
    slug: str
    description: str | None = None
    fulfillment_type: str
    status: str
    base_price_amount: int
    base_price_currency: str
    attributes: dict[str, Any]
    urls: list[str] = []  # product image URLs
    created_at: datetime
    updated_at: datetime
    variants: list["ProductVariantResponse"] = []


class ProductVariantCreate(BaseModel):
    sku: str = Field(..., min_length=1)
    attributes: dict[str, Any] | None = {}
    price_override_amount: int | None = None
    price_override_currency: str | None = Field(None, min_length=3, max_length=3)
    inventory_policy: str | None = Field(None, pattern="^(tracked|untracked|unlimited)$")
    quantity_available: int | None = Field(None, ge=0)
    quantity_reserved: int | None = Field(None, ge=0)


class ProductVariantResponse(BaseModel):
    id: str
    product_id: str
    sku: str
    attributes: dict[str, Any]
    price_override_amount: int | None = None
    price_override_currency: str | None = None
    inventory_policy: str
    quantity_available: int | None = None
    created_at: datetime
    updated_at: datetime


class InventoryUpdate(BaseModel):
    quantity_available: int | None = Field(None, ge=0)
    quantity_reserved: int | None = Field(None, ge=0)


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    size: int
    pages: int