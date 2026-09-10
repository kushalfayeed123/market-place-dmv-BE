# app/modules/catalog/service/dependency.py
"""
Dependency injection for catalog service.
Provides FastAPI dependency for injecting the catalog service into routers.
"""

from app.db.session import get_db
from app.modules.catalog.service.base import CatalogService
from app.modules.catalog.service.implementation import CatalogServiceImpl
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_catalog_service(
    db: AsyncSession = get_db_depends,
) -> CatalogService:
    """
    Factory function that creates and returns a CatalogService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of CatalogService (specifically CatalogServiceImpl).
    """
    return CatalogServiceImpl(db)
