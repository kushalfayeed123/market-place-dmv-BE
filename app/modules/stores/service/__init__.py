# app/modules/stores/service/__init__.py
"""
Store service layer.
Provides abstract and concrete implementations for store operations.
"""

from app.modules.stores.service.base import StoreService
from app.modules.stores.service.dependency import get_store_service
from app.modules.stores.service.implementation import StoreServiceImpl

__all__ = ["StoreService", "StoreServiceImpl", "get_store_service"]
