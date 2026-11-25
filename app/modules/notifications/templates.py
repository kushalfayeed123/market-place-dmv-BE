# app/modules/notifications/templates.py
"""Branded email templates for every notification type.

Each template renders ``(subject, plain_text, html)`` from a context dict so all
outbound email is consistently branded and structured. Templates are plain
string formatting — no external templating engine required.

The default layout uses a branded header bar (brand wordmark + accent colour),
a content card, an optional CTA button (when ``action_url`` / ``action_label``
are supplied), and a footer with copyright information.  All user-supplied
values are HTML-escaped via :func:`_esc` to avoid injection.

Usage
-----

````python
from app.modules.notifications.templates import render_email

subject, text, html = render_email(
    "order_confirmation",
    {
        "order_number": "ORD-12345678-123456-1234",
        "total": "123.45",
        "currency": "USD",
        "items_summary": "2× shoes, 1× bag",
        "action_url": "https://app.marketplace.example/orders/ORD-12345678-123456-1234",
        "action_label": "View order",
    },
)
````

````python
from app.core.config import settings
from app.modules.notifications.templates import render_email

subject, text, html = render_email(
    "welcome_email",
    {
        "business_name": "Acme Store",
        "action_url": settings.FRONTEND_URL.rstrip("/"),
        "action_label": "Go to your store",
    },
)
````
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

from app.core.config import settings

BRAND = "Markto"
BRAND_COLOR = "#4f46e5"  # indigo accent
TEXT_COLOR = "#374151"
MUTED_COLOR = "#6b7281"
BG_COLOR = "#f3f4f6"
CARD_BG = "#ffffff"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(value: Any) -> str:
    """Convert a value to string; return ``""`` for ``None``."""
    return "" if value is None else str(value)


def _esc(value: Any) -> str:
    """HTML-escape a value after converting it to string."""
    return escape(_fmt(value))


def _base_url() -> str:
    """Return the canonical base URL for the app (frontend or public)."""
    return (settings.PUBLIC_BASE_URL or settings.FRONTEND_URL or "").rstrip("/")


def _order_url(ctx: dict[str, Any]) -> str:
    """Build a "View order" URL from the context if possible."""
    action = _fmt(ctx.get("action_url"))
    if action:
        return action
    order_ref = _fmt(ctx.get("order_number")) or _fmt(ctx.get("related_order_id"))
    base = _base_url()
    if base and order_ref:
        return f"{base}/orders/{order_ref}"
    return ""


def _fallback_html(subject: str, body: str) -> str:
    """Render a plain branded wrapper around the supplied text (used when a
    type‑specific template cannot render because required context keys are
    missing)."""
    year = datetime.now().year
    return (
        f"<!doctype html>"
        f"<html lang=\"en\">"
        f"<head><meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>"
        f"<title>{_esc(subject)}</title></head>"
        f"<body style=\"margin:0;padding:0;background:{BG_COLOR};"
        f"font-family:'Segoe UI',Arial,Helvetica,sans-serif;\">"
        f"<div style=\"max-width:600px;margin:0 auto;padding:24px 16px;\">"
        f"<div style=\"background:{CARD_BG};border-radius:12px;"
        f"overflow:hidden;box-shadow:0 1px 3px rgba(16,24,40,0.08);\">"
        f"<div style=\"background:{BRAND_COLOR};padding:18px 28px;\">"
        f"<span style=\"color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.5px;\">"
        f"{BRAND}</span></div>"
        f"<div style=\"padding:28px;\">"
        f"<h1 style=\"margin:0 0 16px;font-size:20px;line-height:1.35;color:#111827;\">"
        f"{_esc(subject)}</h1>"
        f"<div style=\"font-size:14px;line-height:1.6;color:{TEXT_COLOR};\">"
        f"{_esc(body)}</div>"
        f"</div>"
        f"<div style=\"background:#f9fafb;border-top:1px solid #e5e7eb;padding:18px 28px;\">"
        f"<p style=\"margin:0 0 6px;font-size:12px;line-height:1.5;color:{MUTED_COLOR};\">"
        f"You're receiving this email because you have a {BRAND} account. If you didn't expect it, you can safely ignore it.</p>"
        f"<p style=\"margin:0;font-size:12px;color:#9ca3af;\">&copy; {year} {BRAND} Marketplace</p>"
        f"</div></div></div></body></html>"
    )


# ---------------------------------------------------------------------------
# Branded HTML wrapper
# ---------------------------------------------------------------------------

def _html_wrap(title: str, body_html: str, action_url: str = "", action_label: str = "") -> str:
    """Render a full branded HTML document.

    Parameters
    ----------
    title:
        The page title (shown in the <h1> and the browser tab).
    body_html:
        The main content HTML (already escaped by the caller).
    action_url:
        Optional URL for a CTA button; when supplied ``action_label`` must also be
        supplied.
    action_label:
        The label for the CTA button.
    """
    cta = ""
    if action_url and action_label:
        cta = (
            f'<p style="margin:24px 0 0;text-align:center;">'
            f'<a href="{_esc(action_url)}" '
            f'style="display:inline-block;background:{BRAND_COLOR};color:#ffffff;'
            'text-decoration:none;font-size:14px;font-weight:600;padding:12px 28px;border-radius:8px;">'
            f'{_esc(action_label)}</a></p>'
        )

    year = datetime.now().year
    return (
        f"<!doctype html>"
        f"<html lang=\"en\">"
        f"<head><meta charset=\"utf-8\"/><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>"
        f"<title>{_esc(title)}</title></head>"
        f"<body style=\"margin:0;padding:0;background:{BG_COLOR};"
        f"font-family:'Segoe UI',Arial,Helvetica,sans-serif;\">"
        f"<div style=\"max-width:600px;margin:0 auto;padding:24px 16px;\">"
        f"<div style=\"background:{CARD_BG};border-radius:12px;"
        f"overflow:hidden;box-shadow:0 1px 3px rgba(16,24,40,0.08);\">"
        f"<div style=\"background:{BRAND_COLOR};padding:18px 28px;\">"
        f"<span style=\"color:#ffffff;font-size:22px;font-weight:700;letter-spacing:0.5px;\">"
        f"{BRAND}</span></div>"
        f"<div style=\"padding:28px;\">"
        f"<h1 style=\"margin:0 0 16px;font-size:20px;line-height:1.35;color:#111827;\">"
        f"{_esc(title)}</h1>"
        f"<div style=\"font-size:14px;line-height:1.6;color:{TEXT_COLOR};\">"
        f"{body_html}</div>"
        f"{cta}"
        f"</div>"
        f"<div style=\"background:#f9fafb;border-top:1px solid #e5e7eb;padding:18px 28px;\">"
        f"<p style=\"margin:0 0 6px;font-size:12px;line-height:1.5;color:{MUTED_COLOR};\">"
        f"You're receiving this email because you have a {BRAND} account. If you didn't expect it, you can safely ignore it.</p>"
        f"<p style=\"margin:0;font-size:12px;color:#9ca3af;\">&copy; {year} {BRAND} Marketplace</p>"
        f"</div></div></div></body></html>"
    )


# ---------------------------------------------------------------------------
# Per‑type renderers
# ---------------------------------------------------------------------------

def render_email(notification_type: str, context: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """Render ``(subject, plain_text, html)`` for a notification type + context.

    Parameters
    ----------
    notification_type:
        One of the :class:`~app.models.notification.NotificationType` values
        (e.g. ``"order_confirmation"``).
    context:
        A mapping of variable names used by the template.  Any key that a
        particular branch needs (``order_number``, ``total``, ``currency``,
        ``items_summary``, ``status``, ``detail``, ``amount``, ``bank``,
        ``business_name``, ``action_url``, ``action_label``, ``subject``,
        ``body``) should be supplied here.  Missing required keys cause the
        branch to fall back to a generic branded wrapper.

    Returns
    -------
    subject, text, html
        A three‑tuple of strings.  ``html`` always contains a full HTML document
        that follows the project's branding guidelines.
    """
    ctx: dict[str, Any] = dict(context) if context else {}
    # Seed fallback values first, so that any branch can safely reference
    # ``ctx["subject"]`` / ``ctx["body"]`` without raising KeyError.
    ctx.setdefault("subject", ctx.get("subject") or f"{BRAND} notification")
    ctx.setdefault("body", ctx.get("body") or "")

    t = notification_type

    # ── welcome_email ──
    if t == "welcome_email":
        business_name = _fmt(ctx.get("business_name"))
        action_url = _fmt(ctx.get("action_url"))
        action_label = _fmt(ctx.get("action_label"))
        subject = f"Welcome to {_esc(BRAND)}, {_esc(business_name)}!" if business_name else f"Welcome to {BRAND}!"
        text = (
            f"Hi {_esc(business_name)}, welcome to {BRAND}! "
            "Your store is ready — add products, set up your payout account, and start selling."
        ) if business_name else "This is a test notification email. If you received this, email delivery is working."
        html = _html_wrap(
            subject,
            f"<p>Hi <b>{_esc(business_name)}</b>, welcome to {BRAND}!</p>"
            "<p>Your store is ready. Add products, set up your payout account, and start selling.</p>",
            action_url=action_url,
            action_label=action_label,
        )
        return subject, text, html

    # ── test_email ──
    if t == "test_email":
        subject = f"Test email from {BRAND}"
        text = "This is a test notification email. If you received this, email delivery is working."
        html = _html_wrap(
            subject,
            "<p>This is a <b>test</b> notification email. Email delivery is working.</p>",
        )
        return subject, text, html

    # ── order_confirmation ──
    if t == "order_confirmation":
        onum = _fmt(ctx.get("order_number"))
        total = _fmt(ctx.get("total"))
        currency = _fmt(ctx.get("currency"))
        items = _fmt(ctx.get("items_summary"))
        action_url = _order_url(ctx)
        action_label = _fmt(ctx.get("action_label"))
        subject = f"Order {onum} confirmed" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"Your order {onum} has been placed. "
            f"Total: {total} {currency}. Items: {items}."
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>Your order <b>{_esc(onum)}</b> has been placed.</p>"
            + (f"<p>Total: <b>{_esc(total)} {_esc(currency)}</b><br/>"
               f"Items: {_esc(items)}</p>" if onum else ""),
            action_url=action_url,
            action_label=action_label,
        )
        return subject, text, html

    # ── merchant_new_order ──
    if t == "merchant_new_order":
        onum = _fmt(ctx.get("order_number"))
        total = _fmt(ctx.get("total"))
        currency = _fmt(ctx.get("currency"))
        action_url = _order_url(ctx)
        action_label = _fmt(ctx.get("action_label"))
        subject = f"New order {onum} received" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"You received a new order {onum} "
            f"totaling {total} {currency}."
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>You received a new order <b>{_esc(onum)}</b>.</p>"
            + (f"<p>Total: <b>{_esc(total)} {_esc(currency)}</b></p>" if onum else ""),
            action_url=action_url,
            action_label=action_label,
        )
        return subject, text, html

    # ── payment_confirmed ──
    if t == "payment_confirmed":
        onum = _fmt(ctx.get("order_number"))
        subject = f"Your payment for order {onum} has been confirmed" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"Your payment for order {onum} has been confirmed. Your order is now being prepared."
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>Your payment for order <b>{_esc(onum)}</b> has been confirmed.</p>"
            "<p>Your order is now being prepared for fulfillment.</p>",
        )
        return subject, text, html

    # ── payment_failed ──
    if t == "payment_failed":
        onum = _fmt(ctx.get("order_number"))
        subject = f"Your payment for order {onum} could not be completed" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"Your payment for order {onum} could not be completed. Please try again."
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>Your payment for order <b>{_esc(onum)}</b> could not be completed.</p>"
            "<p>Please try again or contact support.</p>",
        )
        return subject, text, html

    # ── shipping_update ──
    if t == "shipping_update":
        onum = _fmt(ctx.get("order_number"))
        status = _fmt(ctx.get("status"))
        detail = _fmt(ctx.get("detail"))
        subject = f"Shipping update — Order {onum}" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"Order {onum}: {status}. {detail or ''}"
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>Order <b>{_esc(onum)}</b>: <b>{_esc(status)}</b></p>"
            + (f"<p>{_esc(detail)}</p>" if detail else ""),
        )
        return subject, text, html

    # ── order_completed ──
    if t == "order_completed":
        onum = _fmt(ctx.get("order_number"))
        subject = f"Order {onum} delivered" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = (
            f"Your order {onum} has been delivered. Thank you for shopping with {BRAND}!"
        ) if onum else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        html = _html_wrap(
            subject,
            f"<p>Your order <b>{_esc(onum)}</b> has been delivered.</p>"
            + f"<p>Thank you for shopping with {BRAND}!</p>",
        )
        return subject, text, html

    # ── order_cancelled ──
    if t == "order_cancelled":
        onum = _fmt(ctx.get("order_number"))
        subject = f"Order {onum} cancelled" if onum else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = f"Your order {onum} has been cancelled."
        html = _html_wrap(subject, f"<p>Your order <b>{_esc(onum)}</b> has been cancelled.</p>")
        return subject, text, html

    # ── refund_issued ──
    if t == "refund_issued":
        onum = _fmt(ctx.get("order_number"))
        amount = _fmt(ctx.get("amount"))
        currency = _fmt(ctx.get("currency"))
        subject = (
            f"A refund of {amount} {currency} was issued for order {onum}"
            if onum and amount
            else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        )
        text = (
            f"A refund of {amount} {currency} was issued for order {onum}."
            if onum and amount
            else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        )
        html = _html_wrap(
            subject,
            f"<p>A refund of <b>{_esc(amount)} {_esc(currency)}</b> was issued for order "
            f"<b>{_esc(onum)}</b>.</p>",
        )
        return subject, text, html

    # ── payout_released / payout_paid ──
    if t in ("payout_released", "payout_paid"):
        amount = _fmt(ctx.get("amount"))
        currency = _fmt(ctx.get("currency"))
        bank = _fmt(ctx.get("bank"))
        status = _fmt(ctx.get("status", t.replace("_", " ").title()))
        subject = (
            f"Payout {status} — {amount} {currency}"
            if amount
            else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        )
        text = (
            f"A payout of {amount} {currency} has been sent to your registered account ({bank})."
            if amount
            else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        )
        html = _html_wrap(
            subject,
            f"<p>A payout of <b>{_esc(amount)} {_esc(currency)}</b> has been sent to your "
            f"registered account ({_esc(bank)}).</p>",
        )
        return subject, text, html

    # ── digital_delivery_ready ──
    if t == "digital_delivery_ready":
        onum = _fmt(ctx.get("order_number"))
        subject = (
            f"Your digital purchase is ready — Order {onum}"
            if onum
            else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        )
        text = (
            f"Your digital item for order {onum} is ready to download."
            if onum
            else (_fmt(ctx.get("subject")) or f"{BRAND} notification")
        )
        html = _html_wrap(
            subject,
            f"<p>Your digital item for order <b>{_esc(onum)}</b> is ready to download.</p>",
        )
        return subject, text, html

    # ── proof_of_payment_submitted ──
    if t == "proof_of_payment_submitted":
        onum = _fmt(ctx.get("order_number"))
        subject = (
            f"Proof of payment for order {onum}"
            if onum
            else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        )
        text = "A buyer has submitted proof of payment. Please review and approve."
        html = _html_wrap(
            subject,
            f"<p>A buyer submitted proof of payment for order <b>{_esc(onum)}</b>.</p>"
            "<p>Please review and approve.</p>",
        )
        return subject, text, html

    # ── support_ticket ──
    if t == "support_ticket":
        event_type = _fmt(ctx.get("event_type"))
        ticket_number = _fmt(ctx.get("ticket_number"))
        subject = f"[Support] {event_type} — {ticket_number}" if event_type and ticket_number else _fmt(ctx.get("subject")) or f"{BRAND} notification"
        text = _fmt(ctx.get("body")) or f"Support event {event_type} — {ticket_number}"
        html = _html_wrap(
            subject,
            f"<pre style=\"margin:0;padding:12px;background:#f1f5f9;border-radius:6px;font-family:monospace;color:#111827;font-size:13px;\">{_esc(_fmt(ctx.get('payload_json')))}</pre>",
        )
        return subject, text, html

    # ── generic fallback ──
    subject = _fmt(ctx.get("subject")) or f"{BRAND} notification"
    text = _fmt(ctx.get("body")) or subject
    html = _fallback_html(subject, text)
    return subject, text, html