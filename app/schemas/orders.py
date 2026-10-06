# app/schemas/orders.py
"""
Pydantic schemas for orders requests and responses.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CartItem(BaseModel):
    variant_id: str
    quantity: int = Field(..., gt=0)


class Cart(BaseModel):
    items: list[CartItem]


class CheckoutRequest(BaseModel):
    items: list[CartItem]
    # In a real implementation, we would also include shipping info, payment method, etc.


class CheckoutResponse(BaseModel):
    id: str
    order_number: str
    status: str
    currency: str
    total_amount: int  # Minor units
    idempotency_key: str
    created_at: datetime
    items: list[dict]  # Order item details


class OrderResponse(BaseModel):
    id: str
    order_number: str
    buyer_id: str
    status: str
    currency: str
    total_amount: int  # Minor units
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime
    items: list[dict]  # Order item details


class OrderItemResponse(BaseModel):
    id: str
    order_id: str
    product_id: str
    variant_id: str | None = None
    merchant_id: str
    quantity: int
    unit_price: int  # Minor units
    currency: str
    line_total: int  # Minor units