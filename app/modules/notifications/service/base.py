# app/modules/notifications/service/base.py
"""Abstract base class for the notifications service."""

from abc import ABC, abstractmethod
from typing import Optional

from app.schemas.notification import NotificationCreate, NotificationResponse


class NotificationService(ABC):
    """Interface for creating/querying notification records."""

    @abstractmethod
    async def create_notification(self, data: NotificationCreate) -> NotificationResponse:
        """Create a notification record (status defaults to pending)."""
        ...

    @abstractmethod
    async def get_notification(self, notification_id: str) -> Optional[NotificationResponse]:
        """Fetch a single notification by id."""
        ...

    @abstractmethod
    async def list_user_notifications(
        self,
        user_id: str,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
    ) -> list[NotificationResponse]:
        """List notifications addressed to a user, newest first."""
        ...

    @abstractmethod
    async def mark_sent(self, notification_id: str, provider: str, provider_reference: str) -> Optional[NotificationResponse]:
        """Mark a notification as sent by the background worker."""
        ...

    @abstractmethod
    async def list_pending_for_worker(
        self, limit: int = 100
    ) -> list[NotificationResponse]:
        """Claim pending notifications suitable for dispatch by the worker."""
        ...
