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
