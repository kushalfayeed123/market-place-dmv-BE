# app/modules/payments/service/dependency.py
"""
Dependency injection for payment service.
Provides FastAPI dependency for injecting the payment service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.payments.service.base import PaymentService
from app.modules.payments.service.implementation import PaymentServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_payment_service(
    db: AsyncSession = get_db_depends,
) -> PaymentService:
    """
    Factory function that creates and returns a PaymentService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of PaymentService (specifically PaymentServiceImpl).
    """
    return PaymentServiceImpl(db)
