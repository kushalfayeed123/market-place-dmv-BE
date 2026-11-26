"""Tests for branded email templates and service-layer email templating."""

import pytest

from app.models.notification import NotificationType
from app.modules.notifications.service.implementation import NotificationServiceImpl
from app.modules.notifications.templates import BRAND, render_email
from app.schemas.notification import NotificationCreate

TEST_USER_ID = "12345678-1234-1234-1234-123456789012"

FULL_CONTEXT = {
    "order_number": "ORD-20260101-123456-abcd",
    "total": "4500",
    "currency": "NGN",
    "items_summary": "2× shoes",
    "status": "Shipped",
    "detail": "via DHL (tracking: 1234567890)",
    "amount": "4500",
    "bank": "Test Bank ****1234",
    "business_name": "Acme Store",
    "action_url": "https://app.example.com/orders/ORD-20260101-123456-abcd",
    "action_label": "View order",
}

TEMPLATE_TYPES = [
    "welcome_email",
    "test_email",
    "support_ticket",
    "proof_of_payment_submitted",
] + [t.value for t in NotificationType]

# Types whose template body is centred on the order number.
ORDER_TYPES = {
    "order_confirmation", "merchant_new_order", "payment_confirmed",
    "payment_failed", "shipping_update", "order_completed", "order_cancelled",
    "refund_issued", "digital_delivery_ready", "proof_of_payment_submitted",
}


@pytest.mark.parametrize("t", TEMPLATE_TYPES)
def test_every_type_renders_branded_html(t):
    """Every notification type renders subject/text/html with the brand shell."""
    subject, text, html = render_email(t, dict(FULL_CONTEXT, payload_json="{}"))
    assert subject
    assert text
    assert html.startswith("<!doctype html>")
    assert BRAND in html
    if t in ORDER_TYPES:
        assert "ORD-20260101-123456-abcd" in html


def test_html_escapes_user_supplied_values():
    """Malicious context values must not inject markup into the HTML."""
    _, _, html = render_email(
        "welcome_email", {"business_name": "<script>alert(1)</script>"}
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cta_button_rendered_when_action_supplied():
    _, _, html = render_email("order_confirmation", dict(FULL_CONTEXT))
    assert "View order" in html
    assert "https://app.example.com/orders/ORD-20260101-123456-abcd" in html


def test_merchant_order_cta_links_to_dashboard_order_detail(monkeypatch):
    from app.modules.notifications import templates

    monkeypatch.setattr(templates.settings, "PUBLIC_BASE_URL", "")
    monkeypatch.setattr(templates.settings, "FRONTEND_URL", "https://shop.example.com")
    _, _, html = render_email(
        "merchant_new_order",
        {
            "order_number": "ORD-20260101-123456-abcd",
            "related_order_id": "12345678-1234-1234-1234-123456789012",
            "action_label": "View order",
        },
    )

    assert (
        "https://shop.example.com/merchant/orders/"
        "12345678-1234-1234-1234-123456789012"
    ) in html
    assert "/orders/ORD-20260101-123456-abcd" not in html


def test_order_email_formats_minor_units_as_major_currency():
    _, text, html = render_email(
        "order_confirmation",
        {
            "order_number": "ORD-20260101-123456-abcd",
            "total": "3000000",
            "currency": "NGN",
            "items_summary": "1 item",
        },
    )

    assert "30,000.00 NGN" in text
    assert "30,000.00 NGN" in html


def test_unknown_type_falls_back_to_branded_wrapper():
    subject, text, html = render_email(
        "some_custom_type", {"subject": "Hello", "body": "Plain body text"}
    )
    assert subject == "Hello"
    assert text == "Plain body text"
    assert BRAND in html
    assert "Plain body text" in html


@pytest.mark.asyncio
async def test_create_notification_templates_email_html(db):
    """Email notifications created without html_body get branded HTML."""
    service = NotificationServiceImpl(db)
    created = await service.create_notification(
        NotificationCreate(
            user_id=TEST_USER_ID,
            type=NotificationType.ORDER_CONFIRMATION.value,
            channel="email",
            subject="Order ORD-1 confirmed",
            body="Your order has been placed.",
            payload={"order_number": "ORD-1"},
        )
    )
    assert created.html_body is not None
    assert created.html_body.startswith("<!doctype html>")
    assert BRAND in created.html_body
    assert "ORD-1" in created.html_body


@pytest.mark.asyncio
async def test_create_notification_non_email_has_no_html(db):
    """Non-email channels must not get an HTML body."""
    service = NotificationServiceImpl(db)
    created = await service.create_notification(
        NotificationCreate(
            user_id=TEST_USER_ID,
            type=NotificationType.ORDER_CONFIRMATION.value,
            channel="in_app",
            subject="Order confirmed",
            body="Your order has been placed.",
        )
    )
    assert created.html_body is None


@pytest.mark.asyncio
async def test_create_notification_keeps_explicit_html(db):
    """An explicitly provided html_body is never overwritten."""
    service = NotificationServiceImpl(db)
    created = await service.create_notification(
        NotificationCreate(
            user_id=TEST_USER_ID,
            type="custom",
            channel="email",
            subject="Hi",
            body="Body",
            html_body="<p>custom</p>",
        )
    )
    assert created.html_body == "<p>custom</p>"
