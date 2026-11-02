"""Poll and deliver pending notifications using replaceable channel adapters.

Run as a standalone worker with:
    python -m app.workers.notification_worker
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.modules.notifications.delivery import NotificationDelivery
from app.modules.notifications.service.base import NotificationService
from app.modules.notifications.service.implementation import NotificationServiceImpl
from app.models.notification import NotificationChannel
from app.schemas.notification import NotificationResponse

logger = logging.getLogger(__name__)


class NotificationWorker:
    """Claim notification records and dispatch them through channel adapters."""

    def __init__(
        self,
        check_interval: int = 10,
        batch_size: int = 100,
        session_factory: Callable = AsyncSessionLocal,
        service_factory: Callable[[AsyncSession], NotificationService] = (
            NotificationServiceImpl
        ),
        delivery: NotificationDelivery | None = None,
    ):
        self.check_interval = check_interval
        self.batch_size = batch_size
        self._session_factory = session_factory
        self._service_factory = service_factory
        self._delivery = delivery or NotificationDelivery()
        self.running = False

    async def start(self) -> None:
        """Poll continuously until stop() is called."""
        self.running = True
        logger.info("Starting notification worker")
        while self.running:
            try:
                await self.process_batch()
            except Exception:
                logger.exception("Notification worker cycle failed")
            await asyncio.sleep(self.check_interval)

    def stop(self) -> None:
        self.running = False
        logger.info("Stopping notification worker")

    async def process_batch(self) -> int:
        """Claim and dispatch one batch; return the number successfully sent."""
        sent = 0
        async with self._session_factory() as db:
            service = self._service_factory(db)
            pending = await service.list_pending_for_worker(limit=self.batch_size)
            for notification in pending:
                if await self._dispatch(service, notification, db):
                    sent += 1
        return sent

    async def _dispatch(
        self,
        service: NotificationService,
        notification: NotificationResponse,
        db: AsyncSession,
    ) -> bool:
        """Deliver one claimed notification and persist its outcome."""
        try:
            recipient = None
            if notification.channel != NotificationChannel.IN_APP.value:
                recipient = await service.get_recipient_address(notification)
            receipt = await self._delivery.send(notification, recipient)
            updated = await service.mark_sent(
                notification.id, receipt.provider, receipt.reference
            )
            if updated is None:
                raise RuntimeError(
                    f"Notification {notification.id} disappeared after delivery"
                )
            logger.info(
                "Sent %s notification (id=%s, channel=%s, provider=%s)",
                notification.type,
                notification.id,
                notification.channel,
                receipt.provider,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to send %s notification (id=%s, channel=%s)",
                notification.type,
                notification.id,
                notification.channel,
            )
            await db.rollback()
            try:
                failed = await service.mark_failed(notification.id)
            except Exception:
                await db.rollback()
                logger.exception(
                    "Could not persist failed status for notification %s",
                    notification.id,
                )
                raise
            if not failed:
                logger.warning(
                    "Notification %s was no longer in sending state",
                    notification.id,
                )
            return False


notification_worker = NotificationWorker()


async def start_notification_worker() -> None:
    await notification_worker.start()


def stop_notification_worker() -> None:
    notification_worker.stop()


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(start_notification_worker())


if __name__ == "__main__":
    run()
