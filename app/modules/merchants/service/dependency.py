# app/modules/merchants/service/dependency.py
"""
Dependency injection for merchant service.
Provides FastAPI dependency for injecting the merchant service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.implementation import MerchantServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_merchant_service(
    db: AsyncSession = get_db_depends,
) -> MerchantService:
    """
    Factory function that creates and returns a MerchantService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of MerchantService (specifically MerchantServiceImpl).
    """
    return MerchantServiceImpl(db)
