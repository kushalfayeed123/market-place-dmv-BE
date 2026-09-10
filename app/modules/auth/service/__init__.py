# app/modules/auth/service/__init__.py
"""
Auth service layer.
Provides abstract and concrete implementations for authentication operations.
"""

from app.modules.auth.service.dependency import get_auth_service

from app.modules.auth.service.base import AuthService
from app.modules.auth.service.implementation import AuthServiceImpl

__all__ = ["AuthService", "AuthServiceImpl", "get_auth_service"]
