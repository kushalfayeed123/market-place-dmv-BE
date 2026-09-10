# app/modules/fulfillment/service/dependency.py
"""
Dependency injection for fulfillment service.
Provides FastAPI dependency for injecting the fulfillment service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.fulfillment.service.base import FulfillmentService
from app.modules.fulfillment.service.implementation import FulfillmentServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_fulfillment_service(
    db: AsyncSession = get_db_depends,
) -> FulfillmentService:
    """
    Factory function that creates and returns a FulfillmentService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of FulfillmentService (specifically FulfillmentServiceImpl).
    """
    return FulfillmentServiceImpl(db)
