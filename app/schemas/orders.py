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
    item_count: int = 0
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
    item_count: int = 0
    merchant_id: str | None = None
    merchant_name: str | None = None
    payment_status: str | None = None
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