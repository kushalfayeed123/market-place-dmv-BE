# app/modules/notifications/service/__init__.py
"""
Notifications service layer.
Provides abstract and concrete implementations for notification operations.
"""

from app.modules.notifications.service.base import NotificationService
from app.modules.notifications.service.dependency import get_notification_service
from app.modules.notifications.service.implementation import NotificationServiceImpl

__all__ = ["NotificationService", "NotificationServiceImpl", "get_notification_service"]