# app/models/notification.py
"""
Notification model — platform messages (email, SMS, push, and in-app) persisted
before a background worker dispatches them through configured channel providers.
"""

from datetime import datetime
from enum import Enum as PyEnum

from app.db.base import BaseModel
from app.db.types import UUID, BIGINT
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)


class NotificationChannel(PyEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"


class NotificationStatus(PyEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"


class NotificationType(PyEnum):
    ORDER_CONFIRMATION = "order_confirmation"
    PAYMENT_CONFIRMED = "payment_confirmed"
    PAYMENT_FAILED = "payment_failed"
    SHIPPING_UPDATE = "shipping_update"
    ORDER_CANCELLED = "order_cancelled"
    REFUND_ISSUED = "refund_issued"
    MERCHANT_NEW_ORDER = "merchant_new_order"
    DIGITAL_DELIVERY_READY = "digital_delivery_ready"
    ORDER_COMPLETED = "order_completed"
    PAYOUT_RELEASED = "payout_released"


class Notification(BaseModel):
    __tablename__ = "notifications"

    # Recipient — either a user (buyer) or a merchant. At least one should be set.
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    type = Column(String(50), nullable=False)  # NotificationType value
    channel = Column(String(20), nullable=False, default=NotificationChannel.EMAIL.value)
    status = Column(
        String(20), nullable=False, default=NotificationStatus.PENDING.value, index=True
    )

    # Human-readable envelope
    subject = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)  # plain-text body (markdown ok)
    html_body = Column(Text, nullable=True)  # optional HTML body

    # Optional related entities (for traceability / deep-linking)
    related_order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_payment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("payment_transactions.id", ondelete="SET NULL"),
        nullable=True,
    )
    related_product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    # Provider bookkeeping (populated by the worker when it "sends")
    provider = Column(String(50), nullable=True)
    provider_reference = Column(String(255), nullable=True)
    # Extra context JSON stored as Text (project "JSONB-equivalent" convention)
    payload = Column(Text, nullable=True, default="{}")
    cost_units = Column(BIGINT, nullable=True)  # cost in minor units of notification currency
    sent_at = Column(DateTime(timezone=True), nullable=True)

    # Idempotency: a given (type, related_order_id, channel) should only be sent once.
    __table_args__ = (
        Index("idx_notifications_user_status", "user_id", "status"),
        Index("idx_notifications_merchant_status", "merchant_id", "status"),
        Index("idx_notifications_type", "type"),
        Index("idx_notifications_created_at", text("created_at DESC")),
                CheckConstraint("cost_units >= 0", name="ck_notifications_cost_non_negative"),
    )

    def __repr__(self):
        return (
            f"<Notification(id={self.id}, type={self.type}, channel={self.channel}, "
            f"status={self.status})>"
        )
