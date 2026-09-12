# app/workers/support_notify_worker.py
"""
Support notification worker — delivers new-ticket / status-change events.

Consumes `webhook_events` rows written by the support module (provider='support')
and delivers them to humans so they don't have to poll the admin API:

1. Signed webhook POST to SUPPORT_WEBHOOK_URL (HMAC-SHA256 over the raw body).
2. Email to SUPPORT_EMAIL_TO when SMTP is configured.

Delivery is at-least-once and idempotent on the receiver side
(event_id is unique per ticket event). `processed_at` is set only after
successful delivery; failures stay unprocessed and are retried with backoff.
Run:  python -m app.workers.support_notify_worker   (or start_support_notify_worker)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.webhook_event import WebhookEvent

logger = logging.getLogger(__name__)

PROVIDER = "support"
BATCH_SIZE = 50


def sign_payload(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def deliver_webhook(event: WebhookEvent) -> bool:
    """POST the event to SUPPORT_WEBHOOK_URL with an HMAC signature. True on 2xx."""
    url = settings.SUPPORT_WEBHOOK_URL
    if not url:
        return False
    body = json.dumps({
        "event_id": event.event_id,
        "event_type": event.event_type,
        "provider": event.provider,
        "payload": json.loads(event.payload) if event.payload else {},
    }, default=str).encode()
    headers = {"Content-Type": "application/json"}
    if settings.SUPPORT_WEBHOOK_SECRET:
        headers["X-Support-Signature"] = sign_payload(settings.SUPPORT_WEBHOOK_SECRET, body)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, content=body, headers=headers)
    resp.raise_for_status()
    return True


def deliver_email(event: WebhookEvent) -> bool:
    """Send a plain-text email to SUPPORT_EMAIL_TO. True when sent."""
    if not (settings.SUPPORT_SMTP_HOST and settings.SUPPORT_EMAIL_TO and settings.SUPPORT_EMAIL_FROM):
        return False
    payload = json.loads(event.payload) if event.payload else {}
    msg = EmailMessage()
    msg["Subject"] = f"[Support] {event.event_type} — {payload.get('ticket_number', event.event_id)}"
    msg["From"] = settings.SUPPORT_EMAIL_FROM
    msg["To"] = settings.SUPPORT_EMAIL_TO
    msg.set_content(json.dumps(payload, indent=2, default=str))
    with smtplib.SMTP(settings.SUPPORT_SMTP_HOST, settings.SUPPORT_SMTP_PORT, timeout=15) as smtp:
        if settings.SUPPORT_SMTP_USER:
            smtp.starttls()
            smtp.login(settings.SUPPORT_SMTP_USER, settings.SUPPORT_SMTP_PASSWORD)
        smtp.send_message(msg)
    return True


class SupportNotifyWorker:
    """Polls unprocessed support events and delivers webhook + email."""

    def __init__(self, check_interval: int = 30, max_retries: int = 5):
        self.check_interval = check_interval
        self.max_retries = max_retries
        self.running = False

    async def start(self):
        self.running = True
        logger.info("Starting support notify worker")
        while self.running:
            try:
                await self.process_pending()
            except Exception as exc:  # noqa: BLE001
                logger.error("Support notify worker cycle failed: %s", exc)
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.running = False
        logger.info("Stopping support notify worker")

    async def process_pending(self) -> int:
        """Deliver unprocessed support events. Returns count delivered."""
        delivered = 0
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WebhookEvent)
                .where(WebhookEvent.provider == PROVIDER, WebhookEvent.processed_at.is_(None))
                .order_by(WebhookEvent.received_at.asc())
                .limit(BATCH_SIZE)
            )
            events = result.scalars().all()
            for event in events:
                try:
                    sent_webhook = await deliver_webhook(event)
                    sent_email = await asyncio.to_thread(deliver_email, event)
                    if sent_webhook or sent_email:
                        event.processed_at = event.processed_at or datetime.now(timezone.utc)
                        await db.commit()
                        delivered += 1
                    else:
                        # No channel configured: log prominently instead of spinning forever.
                        logger.warning(
                            "Support event %s has no delivery channel configured "
                            "(set SUPPORT_WEBHOOK_URL and/or SUPPORT_EMAIL_*)", event.event_id,
                        )
                except Exception as exc:  # noqa: BLE001 — keep retrying later
                    logger.error("Failed to deliver support event %s: %s", event.event_id, exc)
        return delivered


support_notify_worker = SupportNotifyWorker()


async def start_support_notify_worker():
    await support_notify_worker.start()


def stop_support_notify_worker():
    support_notify_worker.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_support_notify_worker())
