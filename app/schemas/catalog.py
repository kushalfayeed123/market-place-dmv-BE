# app/schemas/catalog.py
"""
Pydantic schemas for catalog requests and responses.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.product import ALLOWED_PRODUCT_TYPES


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
    # merchant_id / store_id are optional — when omitted they are looked up
    # from the authenticated user's merchant + primary store in the router.
    merchant_id: str | None = None
    store_id: str | None = None
    category_id: str | None = None
    title: str = Field(..., min_length=1)
    slug: str | None = None  # Auto-generated from title when not supplied
    description: str | None = None
    fulfillment_type: str = Field(default="physical", pattern="^(physical|digital|service)$")
    status: str | None = Field(None, pattern="^(draft|active|suspended)$")
    base_price_amount: int = Field(..., ge=0)  # Minor units
    base_price_currency: str = Field(default="NGN", min_length=3, max_length=3)
    attributes: dict[str, Any] | None = {}
    urls: list[str] | None = None
    # One or more product types (e.g. ["physical", "digital"]). A product can
    # appear in every section it was assigned to. Defaults to [fulfillment_type].
    product_types: list[str] | None = None

    model_config = {"validate_assignment": True, "extra": "forbid"}

    @field_validator("product_types")
    @classmethod
    def _validate_product_types(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("product_types must contain at least one type")
        if len(v) != len(set(v)):
            raise ValueError("product_types must not contain duplicates")
        invalid = [t for t in v if t not in ALLOWED_PRODUCT_TYPES]
        if invalid:
            raise ValueError(
                f"Invalid product type(s): {invalid}. Allowed: {list(ALLOWED_PRODUCT_TYPES)}"
            )
        return v

    @model_validator(mode="after")
    def _default_product_types(self) -> "ProductCreate":
        if self.product_types is None:
            self.product_types = [self.fulfillment_type]
        return self


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
    # All product types this product belongs to (e.g. ["physical", "digital"]).
    # A product can appear in every section it was assigned to.
    product_types: list[str] = []
    digital_file_url: str | None = None
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


class DigitalProductFileResponse(BaseModel):
    """Private product file reference; the URL checks purchase access."""

    url: str
    key: str
    filename: str


class DigitalProductFileDownloadResponse(BaseModel):
    """Temporary private reader URL returned after purchase authorization."""

    download_url: str
    expires_in: int
    filename: str
    content_type: str
    format: str


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


class ProductUpdate(BaseModel):
    """Partial-update schema for products. All fields are optional."""
    title: str | None = Field(None, min_length=1)
    slug: str | None = None
    description: str | None = None
    category_id: str | None = None
    fulfillment_type: str | None = Field(None, pattern=r"^(physical|digital|service)$")
    # One or more product types. When provided, replaces the product's types
    # and syncs ``fulfillment_type`` to the first type.
    product_types: list[str] | None = None
    status: str | None = Field(None, pattern=r"^(draft|active|suspended)$")
    base_price_amount: int | None = Field(None, ge=0)
    base_price_currency: str | None = Field(None, min_length=3, max_length=3)
    attributes: dict[str, Any] | None = None
    urls: list[str] | None = None

    model_config = {"extra": "forbid"}

    @field_validator("product_types")
    @classmethod
    def _validate_product_types(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("product_types must contain at least one type")
        if len(v) != len(set(v)):
            raise ValueError("product_types must not contain duplicates")
        invalid = [t for t in v if t not in ALLOWED_PRODUCT_TYPES]
        if invalid:
            raise ValueError(
                f"Invalid product type(s): {invalid}. Allowed: {list(ALLOWED_PRODUCT_TYPES)}"
            )
        return v


class ProductLikeResponse(BaseModel):
    id: str
    user_id: str
    product_id: str
    created_at: datetime


class LikeCountResponse(BaseModel):
    count: int
    liked: bool


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    size: int
    pages: int