"""Provider adapters and channel routing for notification delivery."""

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings
from app.models.notification import NotificationChannel
from app.schemas.notification import NotificationResponse


@dataclass(frozen=True)
class DeliveryReceipt:
    provider: str
    reference: str


class NotificationSender(Protocol):
    async def send(
        self, notification: NotificationResponse, recipient: str | None
    ) -> DeliveryReceipt:
        """Deliver a notification and return the provider's receipt."""


class EmailNotificationSender:
    """Deliver email notifications through the Resend API."""

    async def send(
        self, notification: NotificationResponse, recipient: str | None
    ) -> DeliveryReceipt:
        if not recipient:
            raise ValueError(f"Notification {notification.id} has no email recipient")
        if not settings.RESEND_API_KEY or not settings.RESEND_FROM_EMAIL:
            raise RuntimeError(
                "Resend is not configured; set RESEND_API_KEY and RESEND_FROM_EMAIL"
            )

        payload = {
            "from": settings.RESEND_FROM_EMAIL,
            "to": [recipient],
            "subject": notification.subject,
            "text": notification.body,
        }
        if notification.html_body:
            payload["html"] = notification.html_body

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            )
        response.raise_for_status()
        reference = response.json().get("id")
        if not reference:
            raise RuntimeError("Resend response did not contain an email ID")
        return DeliveryReceipt("resend", reference)


class SmsNotificationSender:
    """Send SMS messages through Twilio's Messages API."""

    async def send(
        self, notification: NotificationResponse, recipient: str | None
    ) -> DeliveryReceipt:
        if not recipient:
            raise ValueError(f"Notification {notification.id} has no phone recipient")
        account_sid = settings.NOTIFICATION_TWILIO_ACCOUNT_SID
        auth_token = settings.NOTIFICATION_TWILIO_AUTH_TOKEN
        from_number = settings.NOTIFICATION_TWILIO_FROM
        if not (account_sid and auth_token and from_number):
            raise RuntimeError("Notification Twilio SMS is not configured")

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        message_body = f"{notification.subject}\n\n{notification.body}"
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                data={"To": recipient, "From": from_number, "Body": message_body},
                auth=(account_sid, auth_token),
            )
        response.raise_for_status()
        reference = response.json().get("sid")
        if not reference:
            raise RuntimeError("Twilio response did not contain a message SID")
        return DeliveryReceipt("twilio", reference)


class InAppNotificationSender:
    """Treat the persisted notification record as its in-app delivery."""

    async def send(
        self, notification: NotificationResponse, recipient: str | None
    ) -> DeliveryReceipt:
        return DeliveryReceipt("in_app", notification.id)


class NotificationDelivery:
    """Routes notifications to replaceable channel-specific sender adapters."""

    def __init__(self, senders: dict[str, NotificationSender] | None = None):
        self._senders = (
            senders
            if senders is not None
            else {
                NotificationChannel.EMAIL.value: EmailNotificationSender(),
                NotificationChannel.SMS.value: SmsNotificationSender(),
                NotificationChannel.IN_APP.value: InAppNotificationSender(),
            }
        )

    async def send(
        self, notification: NotificationResponse, recipient: str | None
    ) -> DeliveryReceipt:
        sender = self._senders.get(notification.channel)
        if sender is None:
            raise ValueError(
                f"Unsupported notification channel: {notification.channel}"
            )
        return await sender.send(notification, recipient)
