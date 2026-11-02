"""Tests for channel routing and notification worker outcomes."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.modules.notifications.delivery import (
    DeliveryReceipt,
    EmailNotificationSender,
    NotificationDelivery,
)
from app.schemas.notification import NotificationResponse
from app.workers.notification_worker import NotificationWorker


def make_notification(channel: str = "email") -> NotificationResponse:
    now = datetime.now(timezone.utc)
    return NotificationResponse(
        id="notification-id",
        user_id="user-id",
        type="order_confirmation",
        channel=channel,
        status="sending",
        subject="Order confirmed",
        body="Your order has been confirmed.",
        provider=None,
        provider_reference=None,
        sent_at=None,
        created_at=now,
        updated_at=now,
    )


class FakeSender:
    def __init__(self, receipt: DeliveryReceipt):
        self.receipt = receipt
        self.recipient = None

    async def send(self, notification, recipient):
        self.recipient = recipient
        return self.receipt


class FakeService:
    def __init__(self, notification):
        self.notification = notification
        self.marked_sent = None
        self.failed = False

    async def get_recipient_address(self, notification):
        return "buyer@example.com"

    async def mark_sent(self, notification_id, provider, provider_reference):
        self.marked_sent = (notification_id, provider, provider_reference)
        return self.notification

    async def mark_failed(self, notification_id):
        self.failed = True
        return True


@pytest.mark.asyncio
async def test_worker_routes_email_and_persists_provider_receipt():
    notification = make_notification()
    sender = FakeSender(DeliveryReceipt("test-provider", "delivery-123"))
    delivery = NotificationDelivery({"email": sender})
    worker = NotificationWorker(delivery=delivery)
    service = FakeService(notification)
    db = AsyncMock()

    sent = await worker._dispatch(service, notification, db)

    assert sent is True
    assert sender.recipient == "buyer@example.com"
    assert service.marked_sent == (
        notification.id,
        "test-provider",
        "delivery-123",
    )
    assert service.failed is False


@pytest.mark.asyncio
async def test_worker_does_not_resolve_recipient_for_in_app():
    notification = make_notification(channel="in_app")
    sender = FakeSender(DeliveryReceipt("in_app", notification.id))
    delivery = NotificationDelivery({"in_app": sender})
    worker = NotificationWorker(delivery=delivery)
    service = FakeService(notification)

    sent = await worker._dispatch(service, notification, AsyncMock())

    assert sent is True
    assert sender.recipient is None


@pytest.mark.asyncio
async def test_worker_marks_failed_delivery():
    notification = make_notification()

    class FailingSender:
        async def send(self, notification, recipient):
            raise RuntimeError("provider unavailable")

    delivery = NotificationDelivery({"email": FailingSender()})
    worker = NotificationWorker(delivery=delivery)
    service = FakeService(notification)
    db = AsyncMock()

    sent = await worker._dispatch(service, notification, db)

    assert sent is False
    assert service.marked_sent is None
    assert service.failed is True
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_resend_email_sender_posts_content_and_returns_provider_id(monkeypatch):
    notification = make_notification()
    notification.html_body = "<p>Order confirmed</p>"
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"id": "resend-message-id"}

    class FakeClient:
        def __init__(self, timeout):
            assert timeout == 15.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, json, headers):
            captured.update(url=url, json=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr(settings, "RESEND_API_KEY", "test-api-key")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "Marketplace <noreply@example.com>")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    receipt = await EmailNotificationSender().send(
        notification, "buyer@example.com"
    )

    assert receipt == DeliveryReceipt("resend", "resend-message-id")
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer test-api-key"
    assert captured["json"] == {
        "from": "Marketplace <noreply@example.com>",
        "to": ["buyer@example.com"],
        "subject": "Order confirmed",
        "text": "Your order has been confirmed.",
        "html": "<p>Order confirmed</p>",
    }


@pytest.mark.asyncio
async def test_resend_email_sender_requires_configuration(monkeypatch):
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    monkeypatch.setattr(settings, "RESEND_FROM_EMAIL", "")

    with pytest.raises(RuntimeError, match="Resend is not configured"):
        await EmailNotificationSender().send(make_notification(), "buyer@example.com")
