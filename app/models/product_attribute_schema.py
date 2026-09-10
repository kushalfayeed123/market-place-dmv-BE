# app/models/product_attribute_schema.py
"""
Product attribute schema model defining JSON-Schema-style validation for product attributes.
"""

from sqlalchemy import Column, Text, ForeignKey
from app.db.types import UUID

from app.db.base import BaseModel


class ProductAttributeSchema(BaseModel):
    __tablename__ = "product_attribute_schemas"

    # Override inherited id from BaseModel — category_id is the sole primary key
    id = None
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True)
    schema = Column(Text, nullable=False)  # JSON-Schema-style definition

    def __repr__(self):
        return f"<ProductAttributeSchema(category_id={self.category_id})>"
