# app/modules/commissions/service/dependency.py
"""
Dependency injection for commission service.
Provides FastAPI dependency for injecting the commission service into routers.
"""

from app.db.session import get_db
from app.modules.commissions.service.base import CommissionService
from app.modules.commissions.service.implementation import CommissionServiceImpl
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_commission_service(
    db: AsyncSession = get_db_depends,
) -> CommissionService:
    """
    Factory function that creates and returns a CommissionService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of CommissionService (specifically CommissionServiceImpl).
    """
    return CommissionServiceImpl(db)
