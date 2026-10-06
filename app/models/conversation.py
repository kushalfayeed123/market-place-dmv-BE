# app/models/conversation.py
"""
Conversation model representing customer–merchant messaging threads.

Each row is a single conversation (thread) between a buyer and a merchant.
Individual messages are stored as ConversationEvent rows (append-only).
"""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)

from app.db.base import BaseModel
from app.db.types import UUID


class Conversation(BaseModel):
    __tablename__ = "conversations"

    merchant_id = Column(
        UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    order_id = Column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    customer_name = Column(String(255), nullable=False)
    last_message = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="unread")

    __table_args__ = (
        Index("idx_conversations_merchant", merchant_id),
        Index("idx_conversations_status", status),
    )

    def __repr__(self):
        return f"<Conversation(id={self.id}, merchant_id={self.merchant_id}, customer={self.customer_name}, status={self.status})>"