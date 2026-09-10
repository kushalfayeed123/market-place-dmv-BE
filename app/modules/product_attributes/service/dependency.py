# app/modules/product_attributes/service/dependency.py
"""
Dependency injection for product attribute schema service.
"""

from app.db.session import get_db
from app.modules.product_attributes.service.base import ProductAttributeSchemaService
from app.modules.product_attributes.service.implementation import (
    ProductAttributeSchemaServiceImpl,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Module-level dependency singleton
get_db_depends = Depends(get_db)


def get_product_attribute_schema_service(
    db: AsyncSession = get_db_depends,
) -> ProductAttributeSchemaService:
    """
    Factory function that creates and returns a ProductAttributeSchemaService instance.
    """
    return ProductAttributeSchemaServiceImpl(db)
