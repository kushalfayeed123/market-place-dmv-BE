# app/workers/notification_worker.py
"""
Background worker for sending notifications.

Since the email/SMS/push providers are not yet wired, this worker *simulates*
delivery: it reads PENDING notifications, flips them to SENDING, records a
provider_reference, and marks them SENT. This lets the full
checkout → payment → confirmation-email flow be exercised end-to-end
without a real email service — the notification is provably recorded and
"delivered" by the worker.

Run with:
    python -m app.workers.notification_worker
"""

import asyncio
import logging
import uuid

from sqlalchemy import update

from app.db.session import AsyncSessionLocal
from app.models.notification import Notification, NotificationStatus
from app.modules.notifications.service.implementation import NotificationServiceImpl

logger = logging.getLogger(__name__)


class NotificationWorker:
    """Polls for pending notifications and dispatches them."""

    def __init__(self, check_interval: int = 10):
        self.check_interval = check_interval
        self.running = False

    async def start(self):
        """Start the worker loop."""
        self.running = True
        logger.info("Starting notification worker")
        while self.running:
            try:
                await self.process_batch()
            except Exception as e:  # noqa: BLE001
                logger.error("Error in notification worker: %s", e)
            await asyncio.sleep(self.check_interval)

    def stop(self):
        self.running = False
        logger.info("Stopping notification worker")

    async def process_batch(self):
        """Claim and dispatch a batch of pending notifications."""
        async with AsyncSessionLocal() as db:
            service = NotificationServiceImpl(db)
            pending = await service.list_pending_for_worker(limit=100)
            if not pending:
                return
            for n in pending:
                await self._dispatch(service, n, db)

    async def _dispatch(self, service, n, db):
        """Simulate sending a single notification and record the outcome."""
        # Simulate an external provider call (e.g. SendGrid / SES stub).
        provider = "stub"
        provider_ref = f"notif_{uuid.uuid4().hex[:12]}"
        try:
            logger.info(
                "Sending %s notification (id=%s) to user=%s merchant=%s via %s",
                n.type, n.id, n.user_id, n.merchant_id, provider,
            )
            await service.mark_sent(n.id, provider, provider_ref)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to send notification %s: %s", n.id, e)
            async with db.begin():
                await db.execute(
                    update(Notification)
                    .where(Notification.id == n.id)
                    .values(status=NotificationStatus.FAILED.value)
                )


def run():
    worker = NotificationWorker()
    asyncio.run(worker.start())


if __name__ == "__main__":
    run()
