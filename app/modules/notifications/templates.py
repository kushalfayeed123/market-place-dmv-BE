# app/modules/notifications/templates.py
"""Email templates for every notification type.

Each template renders ``(subject, text, html)`` from a context dict so all
outbound email is consistently branded and structured. Templates are plain
string formatting — no external templating engine required.
"""

from __future__ import annotations

from typing import Any

BRAND = "Markto"


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def _html_wrap(title: str, body_html: str) -> str:
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f7f9;font-family:Segoe UI,Arial,sans-serif;">
  <div style="max-width:560px;margin:24px auto;background:#ffffff;border-radius:12px;padding:28px;">
    <h1 style="margin:0 0 16px;font-size:20px;color:#111827;">{title}</h1>
    <div style="font-size:14px;line-height:1.6;color:#374151;">{body_html}</div>
    <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">&copy; {BRAND} Marketplace</p>
  </div>
</body></html>"""


def render_email(notification_type: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Render ``(subject, plain_text, html)`` for a notification type + context."""
    t = notification_type
    ctx = context or {}

    if t == "welcome_email":
        subject = f"Welcome to {BRAND}, {_fmt(ctx.get('business_name'))}!"
        text = (
            f"Hi {ctx.get('business_name')}, welcome to {BRAND}! "
            "Your store is ready — add products, set up your payout account, and start selling."
        )
        html = _html_wrap(
            subject,
            f"<p>Hi <b>{_fmt(ctx.get('business_name'))}</b>, welcome to {BRAND}!</p>"
            "<p>Your store is ready. Add products, set up your payout account, and start selling.</p>",
        )
        return subject, text, html

    if t == "test_email":
        subject = f"Test email from {BRAND}"
        text = "This is a test notification email. If you received this, email delivery is working."
        html = _html_wrap(subject, "<p>This is a <b>test</b> notification email. Email delivery is working.</p>")
        return subject, text, html

    if t == "order_confirmation":
        subject = f"Order {ctx.get('order_number')} confirmed"
        text = (
            f"Your order {ctx.get('order_number')} has been placed. "
            f"Total: {ctx.get('total')} {ctx.get('currency')}. Items: {ctx.get('items_summary')}."
        )
        html = _html_wrap(
            subject,
            f"<p>Your order <b>{_fmt(ctx.get('order_number'))}</b> has been placed.</p>"
            f"<p>Total: <b>{_fmt(ctx.get('total'))} {_fmt(ctx.get('currency'))}</b><br/>"
            f"Items: {_fmt(ctx.get('items_summary'))}</p>",
        )
        return subject, text, html

    if t == "merchant_new_order":
        subject = f"New order {ctx.get('order_number')} received"
        text = (
            f"You received a new order {ctx.get('order_number')} "
            f"totaling {ctx.get('total')} {ctx.get('currency')}."
        )
        html = _html_wrap(
            subject,
            f"<p>You received a new order <b>{_fmt(ctx.get('order_number'))}</b>.</p>"
            f"<p>Total: <b>{_fmt(ctx.get('total'))} {_fmt(ctx.get('currency'))}</b></p>"
            "<p>Please log in to fulfill it.</p>",
        )
        return subject, text, html

    if t == "payment_confirmed":
        subject = f"Payment confirmed — Order {ctx.get('order_number')}"
        text = f"Your payment for order {ctx.get('order_number')} has been confirmed. Your order is being prepared."
        html = _html_wrap(
            subject,
            f"<p>Your payment for order <b>{_fmt(ctx.get('order_number'))}</b> has been confirmed.</p>"
            "<p>Your order is now being prepared for fulfillment.</p>",
        )
        return subject, text, html

    if t == "payment_failed":
        subject = f"Payment failed — Order {ctx.get('order_number')}"
        text = f"Your payment for order {ctx.get('order_number')} could not be completed. Please try again."
        html = _html_wrap(
            subject,
            f"<p>Your payment for order <b>{_fmt(ctx.get('order_number'))}</b> could not be completed.</p>"
            "<p>Please try again or contact support.</p>",
        )
        return subject, text, html

    if t == "shipping_update":
        subject = f"Shipping update — Order {ctx.get('order_number')}"
        text = f"Order {ctx.get('order_number')}: {ctx.get('status')}. {ctx.get('detail') or ''}"
        html = _html_wrap(
            subject,
            f"<p>Order <b>{_fmt(ctx.get('order_number'))}</b>: <b>{_fmt(ctx.get('status'))}</b></p>"
            f"<p>{_fmt(ctx.get('detail'))}</p>",
        )
        return subject, text, html

    if t == "order_completed":
        subject = f"Order {ctx.get('order_number')} delivered"
        text = f"Your order {ctx.get('order_number')} has been delivered. Thank you for shopping with {BRAND}!"
        html = _html_wrap(
            subject,
            f"<p>Your order <b>{_fmt(ctx.get('order_number'))}</b> has been delivered.</p>"
            f"<p>Thank you for shopping with {BRAND}!</p>",
        )
        return subject, text, html

    if t == "order_cancelled":
        subject = f"Order {ctx.get('order_number')} cancelled"
        text = f"Your order {ctx.get('order_number')} has been cancelled."
        html = _html_wrap(subject, f"<p>Your order <b>{_fmt(ctx.get('order_number'))}</b> has been cancelled.</p>")
        return subject, text, html

    if t == "refund_issued":
        subject = f"Refund issued — Order {ctx.get('order_number')}"
        text = f"A refund of {ctx.get('amount')} {ctx.get('currency')} was issued for order {ctx.get('order_number')}."
        html = _html_wrap(
            subject,
            f"<p>A refund of <b>{_fmt(ctx.get('amount'))} {_fmt(ctx.get('currency'))}</b> was issued for order "
            f"<b>{_fmt(ctx.get('order_number'))}</b>.</p>",
        )
        return subject, text, html

    if t == "payout_released" or t == "payout_paid":
        subject = f"Payout {ctx.get('status', 'released')} — {ctx.get('amount')} {ctx.get('currency')}"
        text = f"A payout of {ctx.get('amount')} {ctx.get('currency')} has been sent to your registered account ({ctx.get('bank')})."
        html = _html_wrap(
            subject,
            f"<p>A payout of <b>{_fmt(ctx.get('amount'))} {_fmt(ctx.get('currency'))}</b> has been sent to your "
            f"registered account ({_fmt(ctx.get('bank'))}).</p>",
        )
        return subject, text, html

    if t == "digital_delivery_ready":
        subject = f"Your digital purchase is ready — Order {ctx.get('order_number')}"
        text = f"Your digital item for order {ctx.get('order_number')} is ready to download."
        html = _html_wrap(
            subject,
            f"<p>Your digital item for order <b>{_fmt(ctx.get('order_number'))}</b> is ready to download.</p>",
        )
        return subject, text, html

    if t == "proof_of_payment_submitted":
        subject = f"Proof of payment for order {ctx.get('order_number')}"
        text = "A buyer has submitted proof of payment. Please review and approve."
        html = _html_wrap(
            subject,
            f"<p>A buyer submitted proof of payment for order <b>{_fmt(ctx.get('order_number'))}</b>.</p>"
            "<p>Please review and approve.</p>",
        )
        return subject, text, html

    # Fallback generic template
    subject = _fmt(ctx.get("subject")) or f"{BRAND} notification"
    text = _fmt(ctx.get("body")) or subject
    html = _html_wrap(subject, f"<p>{text}</p>")
    return subject, text, html
