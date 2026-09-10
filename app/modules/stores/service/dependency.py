# app/modules/stores/service/dependency.py
"""
Dependency injection for store service.
Provides FastAPI dependency for injecting the store service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.stores.service.base import StoreService
from app.modules.stores.service.implementation import StoreServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_store_service(
    db: AsyncSession = get_db_depends,
) -> StoreService:
    """
    Factory function that creates and returns a StoreService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of StoreService (specifically StoreServiceImpl).
    """
    return StoreServiceImpl(db)
