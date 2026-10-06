# app/schemas/notification.py
"""Pydantic schemas for the notifications module."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class NotificationCreate(BaseModel):
    """Payload for creating a new notification record."""

    user_id: Optional[str] = None
    merchant_id: Optional[str] = None
    type: str  # NotificationType value, e.g. "order_confirmation"
    channel: str = "email"  # NotificationChannel value
    status: str = "pending"  # NotificationStatus value
    subject: str
    body: str
    html_body: Optional[str] = None
    related_order_id: Optional[str] = None
    related_payment_id: Optional[str] = None
    related_product_id: Optional[str] = None
    payload: Optional[dict] = None
    provider: Optional[str] = None


class NotificationResponse(BaseModel):
    """Public notification response."""

    id: str
    user_id: Optional[str] = None
    merchant_id: Optional[str] = None
    type: str
    channel: str
    status: str
    subject: str
    body: str
    html_body: Optional[str] = None
    related_order_id: Optional[str] = None
    related_payment_id: Optional[str] = None
    related_product_id: Optional[str] = None
    provider: Optional[str] = None
    provider_reference: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
