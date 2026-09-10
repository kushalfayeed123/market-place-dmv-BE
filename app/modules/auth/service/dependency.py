# app/modules/auth/service/dependency.py
"""
Dependency injection for auth service.
Provides FastAPI dependency for injecting the auth service into routers.
"""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.auth.service.base import AuthService
from app.modules.auth.service.implementation import AuthServiceImpl

# Module-level dependency singleton (avoids B008 function calls in argument defaults)
get_db_depends = Depends(get_db)


def get_auth_service(
    db: AsyncSession = get_db_depends,
) -> AuthService:
    """
    Factory function that creates and returns an AuthService instance.
    
    This dependency is used by FastAPI to inject the service into route handlers.
    It decouples the router from the concrete service implementation.
    
    Args:
        db: The database session injected by FastAPI's dependency system.
        
    Returns:
        An instance of AuthService (specifically AuthServiceImpl).
    """
    return AuthServiceImpl(db)
