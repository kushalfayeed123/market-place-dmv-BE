# app/models/idempotency_key.py
"""
Idempotency key model for ensuring idempotent operations.
This is operational metadata, not part of the financial ledger.
"""

from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from app.db.types import UUID
import uuid
from sqlalchemy.sql import func
from datetime import datetime, timedelta, timezone

from app.db.base import BaseModel

class IdempotencyKey(BaseModel):
    __tablename__ = "idempotency_keys"
    
    # VARCHAR(255): unique + indexed column, MySQL cannot index TEXT without a prefix length
    idempotency_key = Column(String(255), nullable=False, unique=True)
    endpoint = Column(Text, nullable=False)
    request_hash = Column(Text, nullable=False)  # Hash of normalized request body
    status = Column(String(50), nullable=False, default='in_progress')  # in_progress | completed | failed
    response_status = Column(Integer, nullable=True)
    response_body = Column(Text, nullable=True)  # JSONB equivalent
    locked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc) + timedelta(hours=24),
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_idempotency_keys_key', idempotency_key),
        Index('idx_idempotency_keys_status', status),
        Index('idx_idempotency_keys_expires', expires_at),
    )
    
    def __repr__(self):
        return f"<IdempotencyKey(id={self.id}, key={self.idempotency_key[:20]}..., status={self.status})>"