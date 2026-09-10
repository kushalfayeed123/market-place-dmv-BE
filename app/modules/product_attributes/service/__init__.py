# app/modules/product_attributes/service/__init__.py
"""
Product attribute schema service layer.
"""

from app.modules.product_attributes.service.base import ProductAttributeSchemaService
from app.modules.product_attributes.service.dependency import (
    get_product_attribute_schema_service,
)
from app.modules.product_attributes.service.implementation import (
    ProductAttributeSchemaServiceImpl,
)

__all__ = [
    "ProductAttributeSchemaService",
    "ProductAttributeSchemaServiceImpl",
    "get_product_attribute_schema_service",
]
