# app/schemas/share_link.py
"""
Pydantic schemas for merchant share links (store / product-set links).
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ShareLinkCreate(BaseModel):
    """Create a share link. Omit ``product_ids`` for a whole-store link."""

    store_id: str
    product_ids: list[str] = Field(default_factory=list)
    title: Optional[str] = Field(None, max_length=255)


class ShareLinkResponse(BaseModel):
    id: str
    code: str
    merchant_id: str
    store_id: str
    title: Optional[str] = None
    product_ids: list[str] = Field(default_factory=list)
    is_active: str
    # Absolute public URL the merchant can copy and share.
    url: str
    created_at: datetime
    updated_at: datetime


class ShareLinkStoreInfo(BaseModel):
    id: str
    merchant_id: str
    name: str
    slug: str
    branding: dict[str, Any] = Field(default_factory=dict)


class ShareLinkResolvedProduct(BaseModel):
    """A product embedded in a resolved link, in ProductResponse-like shape."""

    id: str
    merchant_id: str
    store_id: str
    store_name: Optional[str] = None
    title: str
    slug: str
    description: Optional[str] = None
    fulfillment_type: str
    product_types: list[str] = Field(default_factory=list)
    status: str
    base_price_amount: int
    base_price_currency: str
    urls: list[str] = Field(default_factory=list)
    variants: list[dict[str, Any]] = Field(default_factory=list)


class ShareLinkResolveResponse(BaseModel):
    """Public payload returned when a visitor opens /s/{code}."""

    code: str
    kind: str  # "store" | "products"
    title: Optional[str] = None
    url: str
    store: ShareLinkStoreInfo
    products: list[ShareLinkResolvedProduct] = Field(default_factory=list)
