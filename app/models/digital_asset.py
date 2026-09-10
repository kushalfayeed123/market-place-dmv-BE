# app/models/digital_asset.py
"""
Digital asset model for storing information about downloadable products.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from app.db.types import UUID
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class DigitalAsset(BaseModel):
    __tablename__ = "digital_assets"
    
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    variant_id = Column(UUID(as_uuid=True), ForeignKey("product_variants.id"), nullable=True)
    storage_key = Column(Text, nullable=False)  # Private R2/S3 object key
    license_type = Column(Text, nullable=False, default='n_downloads')
    max_downloads = Column(Integer, nullable=False, default=5)
    expiry_days = Column(Integer, nullable=True)  # NULL = no expiry
    
    # Indexes
    __table_args__ = (
        Index('idx_digital_assets_product', product_id),
        Index('idx_digital_assets_variant', variant_id),
    )
    
    def __repr__(self):
        return f"<DigitalAsset(id={self.id}, product_id={self.product_id}, storage_key={self.storage_key[:20]}...)>"