# app/models/category.py
"""
Category model for organizing products in a hierarchical structure.
"""


from app.db.base import BaseModel
from app.db.types import UUID
from sqlalchemy import Column, ForeignKey, Index, String


class Category(BaseModel):
    __tablename__ = "categories"
    
    # VARCHAR(255): MySQL cannot index TEXT columns without a prefix length.
    name = Column(String(255), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)
    
    # Indexes
    __table_args__ = (
        Index('idx_categories_name', name),
        Index('idx_categories_parent', parent_id),
    )
    
    def __repr__(self):
        return f"<Category(id={self.id}, name={self.name}, parent_id={self.parent_id})>"