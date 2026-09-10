# app/models/audit_log.py
"""
Audit log model for recording system actions and changes.
"""

from sqlalchemy import Column, String, Text, ForeignKey, Index, text
from app.db.types import UUID

from app.db.base import BaseModel


class AuditLog(BaseModel):
    __tablename__ = "audit_log"

    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    actor_role = Column(Text, nullable=True)
    action = Column(Text, nullable=False)
    # VARCHAR(255): indexed columns, MySQL cannot index TEXT without a prefix length
    target_type = Column(String(255), nullable=False)
    target_id = Column(String(255), nullable=False)
    json_metadata = Column(Text, nullable=True, server_default=text("('{}')"))  # JSONB equivalent

    # Indexes
    __table_args__ = (
        Index('idx_audit_log_actor', actor_id),
        Index('idx_audit_log_target', target_type, target_id),
        Index('idx_audit_log_created_at', 'created_at'),
    )

    def __repr__(self):
        return f"<AuditLog(id={self.id}, action={self.action}, target_type={self.target_type}, target_id={self.target_id})>"
