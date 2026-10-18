# app/modules/payments/service/dependency.py
"""
Dependency injection for payment service.
Provides FastAPI dependency for injecting the payment service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.notifications.service.dependency import get_notification_service
from app.modules.notifications.service.base import NotificationService
from app.modules.payments.service.base import PaymentService
from app.modules.payments.service.implementation import PaymentServiceImpl

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)
get_notification_service_depends = Depends(get_notification_service)


def get_payment_service(
    db: AsyncSession = get_db_depends,
    notification_service: NotificationService = get_notification_service_depends,
) -> PaymentService:
    """
    Factory function that creates and returns a PaymentService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        notification_service: The notification service injected by FastAPI.

    Returns:
        An instance of PaymentService (specifically PaymentServiceImpl).
    """
    return PaymentServiceImpl(db, notification_service)
