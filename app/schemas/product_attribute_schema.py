# app/schemas/product_attribute_schema.py
"""
Pydantic schemas for product attribute schema requests and responses.
"""

from pydantic import BaseModel, Field
from typing import Dict, Any


class ProductAttributeSchemaCreate(BaseModel):
    category_id: str
    schema: Dict[str, Any] = Field(..., description="JSON Schema definition for product attributes")


class ProductAttributeSchemaResponse(BaseModel):
    category_id: str
    schema: Dict[str, Any]
