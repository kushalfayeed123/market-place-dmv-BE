# app/modules/catalog/service/__init__.py
"""
Catalog service layer.
Provides abstract and concrete implementations for catalog operations.
"""

from app.modules.catalog.service.base import CatalogService
from app.modules.catalog.service.dependency import get_catalog_service
from app.modules.catalog.service.implementation import CatalogServiceImpl

__all__ = ["CatalogService", "CatalogServiceImpl", "get_catalog_service"]
