# app/schemas/payments.py
"""
Pydantic schemas for payments requests and responses.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class PaymentProcess(BaseModel):
    order_id: str
    provider: str = Field(..., pattern="^(paystack|flutterwave|stripe)$")
    # In a real implementation, we would include payment method details, customer info, etc.


class PaymentResponse(BaseModel):
    id: str
    order_id: str
    provider: str
    provider_reference: str
    status: str  # initialized | success | failed | refunded
    amount: int  # Minor units
    currency: str
    created_at: datetime


class RefundRequest(BaseModel):
    amount: int | None = Field(None, gt=0)  # If not provided, refund full amount
    reason: str | None = None


class RefundResponse(BaseModel):
    id: str
    order_id: str
    provider: str
    provider_reference: str
    status: str
    amount: int  # Minor units
    currency: str
    created_at: datetime
    original_payment_id: str


class WebhookResponse(BaseModel):
    status: str
    message: str
    event_id: str


class WebhookPayload(BaseModel):
    """Schema for payment webhook request payload.
    
    This model is used by Swagger UI to generate the request body field,
    allowing users to enter the webhook payload directly in the API docs.
    The 'extra' configuration allows provider-specific fields to pass through.
    """
    event: str
    data: dict = {}
    
    model_config = {"extra": "allow"}