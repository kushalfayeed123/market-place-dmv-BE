# app/models/webhook_event.py
"""
Webhook event model for recording incoming webhooks from payment providers.
"""

from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index, UniqueConstraint
from app.db.types import UUID
import uuid
from sqlalchemy.sql import func

from app.db.base import BaseModel

class WebhookEvent(BaseModel):
    __tablename__ = "webhook_events"
    
    provider = Column(String(50), nullable=False)  # e.g., 'paystack'
    event_id = Column(String(255), nullable=False)  # Provider's own event ID or signature hash
    event_type = Column(Text, nullable=False)  # Type of event (e.g., 'charge.success')
    payload = Column(Text, nullable=False)  # JSONB equivalent
    received_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_webhook_events_provider', provider),
        Index('idx_webhook_events_event_id', event_id),
        Index('idx_webhook_events_received_at', received_at),
        UniqueConstraint('provider', 'event_id', name='uq_webhook_events_provider_event_id'),
    )
    
    def __repr__(self):
        return f"<WebhookEvent(id={self.id}, provider={self.provider}, event_type={self.event_type}, received_at={self.received_at})>"