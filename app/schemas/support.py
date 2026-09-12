# app/schemas/support.py
"""
Pydantic schemas for the support ticket module.
"""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class TicketStatus(str, PyEnum):
    NEW = "new"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketPriority(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(str, PyEnum):
    ORDER_ISSUE = "order_issue"
    PAYMENT = "payment"
    REFUND = "refund"
    PRODUCT = "product"
    MERCHANT = "merchant"
    ACCOUNT = "account"
    OTHER = "other"


class TicketEventActor(str, PyEnum):
    AGENT = "agent"
    REQUESTER = "requester"
    ADMIN = "admin"
    SYSTEM = "system"


class SupportTicketCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.MEDIUM
    # Mandatory for anonymous creation; validated in the service layer
    contact_email: Optional[str] = None
    # Optional triage references (agent-supplied, validated as UUIDs server-side)
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    merchant_id: Optional[str] = None
    # Traceability (agent fills these; clients may omit)
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None

    @field_validator("contact_email")
    @classmethod
    def _email_shape(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and ("@" not in v or "." not in v.split("@")[-1]):
            raise ValueError("contact_email must be a valid email address")
        return v


class SupportTicketAdminUpdate(BaseModel):
    """Admin pickup workflow: assign, transition status, add resolution notes."""

    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None


class SupportTicketResponse(BaseModel):
    id: str
    ticket_number: str
    status: str
    priority: str
    category: str
    subject: str
    description: str
    requester_user_id: Optional[str] = None
    contact_email: Optional[str] = None
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    merchant_id: Optional[str] = None
    session_id: Optional[str] = None
    correlation_id: Optional[str] = None
    assigned_to: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SupportTicketEventResponse(BaseModel):
    id: str
    ticket_id: str
    event_type: str
    actor: str
    detail: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
