# app/models/refresh_token.py
"""
Refresh token model for storing hashed refresh tokens.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index
from app.db.types import UUID
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class RefreshToken(BaseModel):
    __tablename__ = "refresh_tokens"
    
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # VARCHAR(255): indexed column, MySQL cannot index TEXT without a prefix length
    token_hash = Column(String(255), nullable=False)  # SHA-256 of the opaque token
    device_info = Column(Text)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True))
    replaced_by = Column(UUID(as_uuid=True), ForeignKey("refresh_tokens.id"))  # Rotation chain
    
    # Indexes
    __table_args__ = (
        Index('idx_refresh_tokens_user', user_id, postgresql_where=(revoked_at.is_(None))),
        Index('idx_refresh_tokens_token_hash', token_hash),
    )
    
    def __repr__(self):
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, revoked_at={self.revoked_at})>"