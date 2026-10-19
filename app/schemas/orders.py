# app/schemas/orders.py
"""
Pydantic schemas for orders requests and responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from enum import Enum as PyEnum


class CartItem(BaseModel):
    variant_id: str
    quantity: int = Field(..., gt=0)


class Cart(BaseModel):
    items: list[CartItem]


class CheckoutRequest(BaseModel):
    items: list[CartItem]
    # Delivery address — required for delivery fulfillment, optional for pickup
    delivery_address: dict | None = Field(
        None,
        description="Delivery address as a JSON object. Required when fulfillment_option is 'delivery'",
    )
    # Fulfillment option: "delivery" or "pickup"
    fulfillment_option: str | None = Field(
        None,
        description="How the order should be fulfilled: 'delivery' or 'pickup'",
    )


class CheckoutResponse(BaseModel):
    id: str
    order_number: str
    status: str
    currency: str
    total_amount: int  # Minor units
    idempotency_key: str
    item_count: int = 0
    created_at: datetime
    items: list[dict]  # Order item details
    delivery_address: dict | None = None
    fulfillment_option: str | None = None


class OrderResponse(BaseModel):
    id: str
    order_number: str
    buyer_id: str
    status: str
    currency: str
    total_amount: int  # Minor units
    idempotency_key: str | None = None
    item_count: int = 0
    merchant_id: str | None = None
    merchant_name: str | None = None
    payment_status: str | None = None
    fulfillment_status: str | None = None
    fulfilled_at: Optional[datetime] = None
    fulfillment_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    items: list[dict]  # Order item details


class DeliveryMethod(str, PyEnum):
    MERCHANT = "merchant"
    THIRD_PARTY = "third_party"


class FulfillOrderRequest(BaseModel):
    """Merchant marks an order's fulfillment complete (all items delivered)."""
    fulfillment_summary: Optional[str] = Field(
        None,
        description="Summary of how the order was fulfilled (carrier, tracking, download link, etc.)",
    )


class FulfillOrderResponse(BaseModel):
    order_id: str
    order_number: str
    status: str
    fulfillment_status: str
    fulfilled_at: Optional[datetime] = None
    message: str


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


class ProofOfPaymentRequest(BaseModel):
    """Payload for submitting proof of payment (bank transfer, cash, etc.)."""
    proof_image_url: str = Field(..., min_length=1, description="URL of the uploaded proof-of-payment image")
    provider: str = Field(..., description="e.g. 'bank_transfer', 'cash', 'paystack'")
    reference: str = Field(..., min_length=1, description="Payment reference / transaction ID from the provider")


class ProofOfPaymentResponse(BaseModel):
    """Response after submitting proof of payment."""
    order_id: str
    order_number: str
    status: str
    payment_id: str
    payment_status: str
    message: str
    created_at: datetime


class OrderApprovalResponse(BaseModel):
    """Response after merchant approves an order."""
    order_id: str
    order_number: str
    status: str
    payment_status: str
    ledger_entries_created: int
    message: str
    updated_at: datetime