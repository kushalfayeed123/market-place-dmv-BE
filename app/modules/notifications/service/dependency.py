# app/modules/notifications/service/dependency.py
"""Dependency injection for the notifications service."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.notifications.service.base import NotificationService
from app.modules.notifications.service.implementation import NotificationServiceImpl

get_db_depends = Depends(get_db)


def get_notification_service(
    db: AsyncSession = get_db_depends,
) -> NotificationService:
    """FastAPI dependency that injects the notifications service."""
    return NotificationServiceImpl(db)
