# app/models/store.py
"""
Store model representing individual storefronts belonging to merchants.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, text
from app.db.types import UUID
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class Store(BaseModel):
    __tablename__ = "stores"
    
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), nullable=False)
    # VARCHAR(255): indexed columns, MySQL cannot index TEXT without a prefix length
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    branding = Column(Text, nullable=False, server_default=text("('{}')"))  # JSONB equivalent
    
    # Indexes
    __table_args__ = (
        Index('idx_stores_merchant', merchant_id),
        Index('idx_stores_slug', slug),
        Index('idx_stores_name', name),
    )
    
    def __repr__(self):
        return f"<Store(id={self.id}, name={self.name}, merchant_id={self.merchant_id})>"