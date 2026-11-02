# app/modules/notifications/service/implementation.py
"""Database-backed implementation of the notifications service."""

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import to_uuid
from app.models.merchant import Merchant
from app.models.notification import Notification, NotificationChannel, NotificationStatus
from app.models.user import User
from app.modules.notifications.service.base import NotificationService
from app.schemas.notification import NotificationCreate, NotificationResponse


class NotificationServiceImpl(NotificationService):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def _to_response(self, n: Notification) -> NotificationResponse:
        payload_raw = n.payload
        payload = None
        if payload_raw:
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
            except (json.JSONDecodeError, TypeError):
                payload = None
        return NotificationResponse(
            id=str(n.id),
            user_id=str(n.user_id) if n.user_id else None,
            merchant_id=str(n.merchant_id) if n.merchant_id else None,
            type=n.type,
            channel=n.channel,
            status=n.status,
            subject=n.subject,
            body=n.body,
            html_body=n.html_body,
            related_order_id=str(n.related_order_id) if n.related_order_id else None,
            related_payment_id=str(n.related_payment_id) if n.related_payment_id else None,
            related_product_id=str(n.related_product_id) if n.related_product_id else None,
            provider=n.provider,
            provider_reference=n.provider_reference,
            sent_at=n.sent_at,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )

    async def create_notification(self, data: NotificationCreate) -> NotificationResponse:
        # Serialize payload to JSON text (project "JSONB-equivalent" convention)
        payload_text = "{}"
        if data.payload is not None:
            payload_text = json.dumps(data.payload)

        n = Notification(
            user_id=to_uuid(data.user_id) if data.user_id else None,
            merchant_id=to_uuid(data.merchant_id) if data.merchant_id else None,
            type=data.type,
            channel=data.channel,
            status=data.status or NotificationStatus.PENDING.value,
            subject=data.subject,
            body=data.body,
            html_body=data.html_body,
            related_order_id=to_uuid(data.related_order_id) if data.related_order_id else None,
            related_payment_id=to_uuid(data.related_payment_id) if data.related_payment_id else None,
            related_product_id=to_uuid(data.related_product_id) if data.related_product_id else None,
            payload=payload_text,
        )
        self._db.add(n)
        await self._db.commit()
        await self._db.refresh(n)
        return await self._to_response(n)

    async def get_notification(self, notification_id: str) -> NotificationResponse | None:
        result = await self._db.execute(
            select(Notification).where(Notification.id == to_uuid(notification_id))
        )
        n = result.scalar_one_or_none()
        return await self._to_response(n) if n else None

    async def list_user_notifications(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> list[NotificationResponse]:
        query = select(Notification).where(Notification.user_id == to_uuid(user_id))
        if status:
            query = query.where(Notification.status == status)
        query = query.order_by(Notification.created_at.desc()).offset(skip).limit(limit)
        result = await self._db.execute(query)
        rows = result.scalars().all()
        return [await self._to_response(n) for n in rows]

    async def mark_sent(
        self, notification_id: str, provider: str, provider_reference: str
    ) -> NotificationResponse | None:
        result = await self._db.execute(
            select(Notification).where(Notification.id == to_uuid(notification_id))
        )
        n = result.scalar_one_or_none()
        if not n:
            return None
        n.status = NotificationStatus.SENT.value
        n.provider = provider
        n.provider_reference = provider_reference
        n.sent_at = datetime.now(timezone.utc)
        self._db.add(n)
        await self._db.commit()
        await self._db.refresh(n)
        return await self._to_response(n)

    async def list_pending_for_worker(self, limit: int = 100) -> list[NotificationResponse]:
        """
        Claim up to *limit* PENDING notifications by transitioning them to
        SENDING, then return the claimed rows.

        SQLAlchemy 2.0 Update objects do not support .limit(), so we
        first select the candidate IDs, then update them in-place.
        """
        # 1. Fetch IDs of pending notifications (ordered, limited)
        claim_result = await self._db.execute(
            select(Notification.id)
            .where(Notification.status == NotificationStatus.PENDING.value)
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        pending_ids = [row[0] for row in claim_result.fetchall()]
        if not pending_ids:
            return []

        # Claim each row conditionally; only this worker's successful claims
        # may be dispatched when multiple worker instances are running.
        claimed_ids = []
        for notification_id in pending_ids:
            claim = await self._db.execute(
                update(Notification)
                .where(Notification.id == notification_id)
                .where(Notification.status == NotificationStatus.PENDING.value)
                .values(status=NotificationStatus.SENDING.value)
            )
            if claim.rowcount == 1:
                claimed_ids.append(notification_id)
        await self._db.commit()

        # 3. Read only rows successfully claimed by this worker
        if not claimed_ids:
            return []
        result = await self._db.execute(
            select(Notification)
            .where(Notification.id.in_(claimed_ids))
            .order_by(Notification.created_at.asc())
        )
        rows = result.scalars().all()
        return [await self._to_response(n) for n in rows]

    async def get_recipient_address(
        self, notification: NotificationResponse
    ) -> str | None:
        """Resolve the address from the user or merchant who owns the notification."""
        if notification.user_id:
            user_id = to_uuid(notification.user_id)
        elif notification.merchant_id:
            merchant_result = await self._db.execute(
                select(Merchant.owner_user_id).where(
                    Merchant.id == to_uuid(notification.merchant_id)
                )
            )
            user_id = merchant_result.scalar_one_or_none()
        else:
            return None

        if user_id is None:
            return None

        address_column = (
            User.email
            if notification.channel == NotificationChannel.EMAIL.value
            else User.phone
        )
        result = await self._db.execute(
            select(address_column).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def mark_failed(self, notification_id: str) -> bool:
        """Mark a notification failed only if it is still claimed for delivery."""
        result = await self._db.execute(
            update(Notification)
            .where(Notification.id == to_uuid(notification_id))
            .where(Notification.status == NotificationStatus.SENDING.value)
            .values(status=NotificationStatus.FAILED.value)
        )
        await self._db.commit()
        return result.rowcount == 1
