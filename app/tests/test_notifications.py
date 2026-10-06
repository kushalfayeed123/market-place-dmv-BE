# app/tests/test_notifications.py
"""Tests for the notifications module -- service layer and order-number generation."""

import re
import uuid

import pytest

from app.models.notification import (
    NotificationStatus,
    NotificationType,
)
from app.modules.notifications.service.implementation import (
    NotificationServiceImpl,
)
from app.schemas.notification import NotificationCreate
from app.modules.orders.service.implementation import _generate_order_number

TEST_USER_ID = "12345678-1234-1234-1234-123456789012"
TEST_MERCHANT_ID = "87654321-4321-4321-4321-210987654321"
TEST_ORDER_ID = "abcdef01-2345-6789-abcd-ef0123456789"


@pytest.fixture
async def notif_service(db):
    """Provide a NotificationServiceImpl backed by the test database."""
    return NotificationServiceImpl(db)

@pytest.mark.asyncio
async def test_create_notification_basic(notif_service):
    """A notification can be created with minimal required fields."""
    data = NotificationCreate(
        user_id=TEST_USER_ID,
        type=NotificationType.ORDER_CONFIRMATION.value,
        channel="email",
        subject="Order confirmed",
        body="Your order has been placed.",
    )
    result = await notif_service.create_notification(data)

    assert result.user_id == TEST_USER_ID
    assert result.type == "order_confirmation"
    assert result.channel == "email"
    assert result.status == "pending"
    assert result.subject == "Order confirmed"
    assert result.body == "Your order has been placed."
    assert result.provider is None
    assert result.provider_reference is None
    assert result.sent_at is None


@pytest.mark.asyncio
async def test_create_notification_for_merchant(notif_service):
    """A merchant-scoped notification can be created."""
    data = NotificationCreate(
        merchant_id=TEST_MERCHANT_ID,
        type=NotificationType.MERCHANT_NEW_ORDER.value,
        subject="New order received",
        body="You have a new order.",
        related_order_id=TEST_ORDER_ID,
    )
    result = await notif_service.create_notification(data)

    assert result.merchant_id == TEST_MERCHANT_ID
    assert result.related_order_id == TEST_ORDER_ID
    assert result.user_id is None

@pytest.mark.asyncio
async def test_get_notification(notif_service):
    """A created notification can be retrieved by ID."""
    data = NotificationCreate(
        user_id=TEST_USER_ID,
        type=NotificationType.PAYMENT_CONFIRMED.value,
        subject="Payment received",
        body="Your payment was confirmed.",
    )
    created = await notif_service.create_notification(data)

    fetched = await notif_service.get_notification(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.type == "payment_confirmed"
    assert fetched.subject == "Payment received"


@pytest.mark.asyncio
async def test_get_notification_not_found(notif_service):
    """Fetching a non-existent notification returns None."""
    fake_id = str(uuid.uuid4())
    result = await notif_service.get_notification(fake_id)
    assert result is None


@pytest.mark.asyncio
async def test_list_user_notifications(notif_service):
    """Notifications are listed for the correct user."""
    for i in range(2):
        await notif_service.create_notification(NotificationCreate(
            user_id=TEST_USER_ID,
            type=NotificationType.ORDER_CONFIRMATION.value,
            subject=f"Subject {i}",
            body=f"Body {i}",
        ))
    await notif_service.create_notification(NotificationCreate(
        user_id=str(uuid.uuid4()),
        type=NotificationType.ORDER_CONFIRMATION.value,
        subject="Other user",
        body="Should not appear",
    ))

    results = await notif_service.list_user_notifications(TEST_USER_ID)
    assert len(results) == 2
    for r in results:
        assert r.user_id == TEST_USER_ID

@pytest.mark.asyncio
async def test_list_user_notifications_with_status_filter(notif_service):
    """The status filter narrows results correctly."""
    await notif_service.create_notification(NotificationCreate(
        user_id=TEST_USER_ID,
        type=NotificationType.ORDER_CONFIRMATION.value,
        status=NotificationStatus.PENDING.value,
        subject="Pending",
        body="Pending body",
    ))
    await notif_service.create_notification(NotificationCreate(
        user_id=TEST_USER_ID,
        type=NotificationType.PAYMENT_CONFIRMED.value,
        status=NotificationStatus.SENT.value,
        subject="Sent",
        body="Sent body",
    ))

    pending = await notif_service.list_user_notifications(
        TEST_USER_ID, status=NotificationStatus.PENDING.value
    )
    sent = await notif_service.list_user_notifications(
        TEST_USER_ID, status=NotificationStatus.SENT.value
    )
    assert len(pending) == 1
    assert len(sent) == 1
    assert pending[0].status == "pending"
    assert sent[0].status == "sent"

@pytest.mark.asyncio
async def test_mark_sent(notif_service):
    """mark_sent flips status to sent and records provider info."""
    data = NotificationCreate(
        user_id=TEST_USER_ID,
        type=NotificationType.ORDER_CONFIRMATION.value,
        subject="Order confirmed",
        body="Body",
    )
    created = await notif_service.create_notification(data)

    updated = await notif_service.mark_sent(
        created.id, provider="stub", provider_reference="notif_abc123"
    )
    assert updated is not None
    assert updated.status == "sent"
    assert updated.provider == "stub"
    assert updated.provider_reference == "notif_abc123"
    assert updated.sent_at is not None


@pytest.mark.asyncio
async def test_mark_sent_not_found(notif_service):
    """mark_sent returns None for a non-existent notification."""
    fake_id = str(uuid.uuid4())
    result = await notif_service.mark_sent(fake_id, "stub", "ref123")
    assert result is None


@pytest.mark.asyncio
async def test_list_pending_for_worker_claims(notif_service):
    """list_pending_for_worker transitions PENDING to SENDING and returns them."""
    for i in range(2):
        await notif_service.create_notification(NotificationCreate(
            user_id=TEST_USER_ID,
            type=NotificationType.ORDER_CONFIRMATION.value,
            subject=f"Subject {i}",
            body=f"Body {i}",
        ))

    pending = await notif_service.list_pending_for_worker(limit=100)
    assert len(pending) == 2
    for n in pending:
        assert n.status == "sending"

    still_pending = await notif_service.list_pending_for_worker(limit=100)
    assert len(still_pending) == 0


@pytest.mark.asyncio
async def test_order_number_generation():
    """_generate_order_number produces correctly formatted, unique numbers."""
    pattern = re.compile(r"^ORD-\d{8}-\d{6}-[a-f0-9]{4}$")
    seen = set()
    # Generate 20 numbers; collisions among 4-hex-char suffixes in the same
    # second are probabilistic, so we keep generating until we have 20 unique
    # ones (bounded to avoid infinite loop).
    attempts = 0
    while len(seen) < 20 and attempts < 200:
        n = _generate_order_number()
        pattern.match(n)  # validates format
        assert pattern.match(n), f"Bad format: {n}"
        seen.add(n)
        attempts += 1
    assert len(seen) == 20


@pytest.mark.asyncio
async def test_notification_model_registered():
    """The Notification model is registered in BaseModel.metadata."""
    from app.db.base import BaseModel
    assert "notifications" in BaseModel.metadata.tables
