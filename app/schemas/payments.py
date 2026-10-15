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
    payment_url: str | None = Field(
        None,
        description="URL the buyer must visit to complete the payment. "
        "May be None for non-redirect providers or after completion.",
    )
    payment_method: str | None = Field(
        None,
        description="Payment method type, e.g. 'card', 'bank_transfer', 'mobile_money'. "
        "Null when not applicable.",
    )


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


class PaymentProviderInfo(BaseModel):
    """Information about a payment provider's availability.

    Returned by ``GET /payments/methods`` so the frontend can render
    provider buttons — enabled ones become clickable, disabled ones
    are greyed out with a "Coming soon" label.
    """
    key: str
    name: str
    implemented: bool = Field(
        ..., description="Whether the provider is currently integrated"
    )
    supported_currencies: list[str] = Field(
        default_factory=list,
        description="ISO 4217 currency codes this provider supports",
    )
    disabled_reason: str | None = Field(
        None,
        description="Why the provider is disabled, if applicable",
    )