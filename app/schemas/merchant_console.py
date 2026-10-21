# app/schemas/merchant_console.py
"""
Pydantic schemas for the merchant-dashboard console and agent endpoints.

These schemas adapt the core domain objects (orders, products, fulfillments,
payouts, disputes, conversations) into the shapes the frontend dashboard
expects — plus the attention/counts endpoint and agent request/response types.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from pydantic import BaseModel, Field


# ── Attention / overview counts ──────────────────────────────────────────

class AttentionResponse(BaseModel):
    orders_to_fulfil: int = 0
    disputes_due: int = 0
    unread_messages: int = 0
    low_stock: int = 0


# ── Merchant-scoped list items (transformed for the frontend) ──────────

class MerchantOrderListItem(BaseModel):
    id: str
    number: str
    customer_name: str
    created_at: datetime
    total: int               # minor units
    currency: str
    status: str


# ── Order detail (merchant-facing, full) ──────────────────────────────────

class MerchantOrderItemDetail(BaseModel):
    id: str
    product_id: str
    product_title: str
    variant_id: Optional[str] = None
    variant_sku: Optional[str] = None
    image_url: Optional[str] = None
    quantity: int
    unit_price: int            # minor units
    currency: str
    line_total: int            # minor units


class MerchantOrderBuyer(BaseModel):
    id: str
    name: str
    email: str
    phone: Optional[str] = None
    avatar_url: Optional[str] = None


class MerchantOrderPayment(BaseModel):
    """Payment record for an order — the merchant-facing "mode of payment"."""
    status: Optional[str] = None       # e.g. success | failed | pending_verification
    provider: Optional[str] = None     # e.g. paystack | bank_transfer | cash
    provider_reference: Optional[str] = None
    amount: Optional[int] = None       # minor units
    currency: Optional[str] = None


class MerchantOrderFulfillment(BaseModel):
    id: str
    status: str
    type: str
    carrier: Optional[str] = None
    tracking_number: Optional[str] = None
    delivery_method: Optional[str] = None
    delivered_at: Optional[datetime] = None


class MerchantOrderDetail(BaseModel):
    id: str
    order_number: str
    status: str
    currency: str
    total_amount: int                  # minor units — full order total
    item_count: int
    created_at: datetime
    updated_at: datetime
    payment_status: Optional[str] = None
    fulfillment_status: Optional[str] = None
    fulfilled_at: Optional[datetime] = None
    fulfillment_summary: Optional[str] = None
    delivery_address: Optional[dict] = None
    idempotency_key: Optional[str] = None
    buyer: MerchantOrderBuyer
    items: list[MerchantOrderItemDetail]
    payment: Optional[MerchantOrderPayment] = None
    fulfillments: list[MerchantOrderFulfillment] = []


class MerchantProductListItem(BaseModel):
    id: str
    title: str
    sku: str
    stock: int
    price: int               # minor units
    currency: str
    status: str


class MerchantShipmentListItem(BaseModel):
    id: str
    order_number: str
    courier: Optional[str] = None
    tracking_code: Optional[str] = None
    updated_at: datetime
    status: str


class PayoutListItem(BaseModel):
    id: str
    reference: str
    bank_account: Optional[str] = None
    created_at: datetime
    amount: int              # minor units
    currency: str
    status: str


class DisputeListItem(BaseModel):
    id: str
    order_number: str
    reason: str
    respond_by: datetime
    amount: int              # minor units
    currency: str
    status: str


class ConversationListItem(BaseModel):
    id: str
    customer_name: str
    last_message: Optional[str] = None
    updated_at: datetime
    status: str


# ── Agent endpoints ──────────────────────────────────────────────────────

class Risk(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionStatus(str, PyEnum):
    PROPOSED = "proposed"
    EXECUTED = "executed"
    DISMISSED = "dismissed"
    FAILED = "failed"


class ProposedAction(BaseModel):
    id: str
    label: str
    summary: str
    risk: Risk = Risk.LOW
    status: ActionStatus = ActionStatus.PROPOSED


class AgentChatResponse(BaseModel):
    reply: str
    proposed_actions: list[ProposedAction] = Field(default_factory=list)


class AgentConfirmResponse(BaseModel):
    ok: bool
    result_summary: str


# ── Payout account status ──────────────────────────────────────────────────

class PayoutAccountStatusResponse(BaseModel):
    """Whether a merchant has at least one active payout (settlement) account.

    Returned by ``GET /merchants/{id}/payout-account-status`` so the merchant
    dashboard can decide whether to show a setup prompt on login.
    """
    merchant_id: str
    has_payout_account: bool
    provider: Optional[str] = None
    currency: Optional[str] = None
    is_active: bool = False
    created_at: Optional[datetime] = None
