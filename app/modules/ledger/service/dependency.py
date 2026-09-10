# app/modules/ledger/service/dependency.py
"""
Dependency injection for ledger service.
Provides FastAPI dependency for injecting the ledger service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.ledger.service.base import LedgerService
from app.modules.ledger.service.implementation import LedgerServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_ledger_service(
    db: AsyncSession = get_db_depends,
) -> LedgerService:
    """
    Factory function that creates and returns a LedgerService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of LedgerService (specifically LedgerServiceImpl).
    """
    return LedgerServiceImpl(db)
