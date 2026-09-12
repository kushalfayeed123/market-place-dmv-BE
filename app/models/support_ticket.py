# app/models/support_ticket.py
"""
Support ticket models — durable, human-picked-up support requests.

Plain business feature, AI-unaware: the agent creates tickets through the
same REST API as any client. Append-only events provide the audit trail.
"""

from enum import Enum as PyEnum

from sqlalchemy import Column, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.db.base import BaseModel
from app.db.types import UUID, ENUM as PgEnum


class TicketStatus(PyEnum):
    NEW = "new"
    TRIAGED = "triaged"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"
    REOPENED = "reopened"


class TicketPriority(PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketCategory(PyEnum):
    ORDER_ISSUE = "order_issue"
    PAYMENT = "payment"
    REFUND = "refund"
    PRODUCT = "product"
    MERCHANT = "merchant"
    ACCOUNT = "account"
    OTHER = "other"


class TicketEventActor(PyEnum):
    AGENT = "agent"
    REQUESTER = "requester"
    ADMIN = "admin"
    SYSTEM = "system"


class SupportTicket(BaseModel):
    __tablename__ = "support_tickets"

    # Human-friendly pickup reference, e.g. TCK-20260911-3f9a2b1c
    # Uniqueness enforced via uq_support_tickets_number (single unique index)
    ticket_number = Column(String(64), nullable=False)
    # status single-col index intentionally omitted: covered by the
    # leftmost column of idx_support_tickets_status_created (status, created_at)
    status = Column(PgEnum(TicketStatus), nullable=False, default=TicketStatus.NEW)
    priority = Column(PgEnum(TicketPriority), nullable=False, default=TicketPriority.MEDIUM, index=True)
    category = Column(PgEnum(TicketCategory), nullable=False, default=TicketCategory.OTHER, index=True)

    subject = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)

    # Requester: authenticated users are linked; anonymous tickets carry a contact email
    # single-col index intentionally omitted: covered by idx_support_tickets_requester
    requester_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    contact_email = Column(String(255), nullable=True)

    # Optional commerce references for triage context (raw ids, agent-supplied)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="SET NULL"), nullable=True, index=True)
    payment_id = Column(UUID(as_uuid=True), ForeignKey("payment_transactions.id", ondelete="SET NULL"), nullable=True, index=True)
    merchant_id = Column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="SET NULL"), nullable=True, index=True)

    # Traceability back to the agent conversation (debug trace lookup)
    session_id = Column(String(64), nullable=True, index=True)
    correlation_id = Column(String(64), nullable=True, index=True)

    # Human workflow
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    resolution_notes = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_support_tickets_status_created", status, "created_at"),
        Index("idx_support_tickets_requester", requester_user_id),
        UniqueConstraint("ticket_number", name="uq_support_tickets_number"),
    )

    def __repr__(self):
        return f"<SupportTicket(id={self.id}, number={self.ticket_number}, status={self.status.value})>"


class SupportTicketEvent(BaseModel):
    """Append-only audit trail for a ticket (never updated, never deleted)."""

    __tablename__ = "support_ticket_events"

    ticket_id = Column(UUID(as_uuid=True), ForeignKey("support_tickets.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(50), nullable=False)  # created | status_changed | assigned | note
    actor = Column(PgEnum(TicketEventActor), nullable=False, default=TicketEventActor.SYSTEM)
    # index=True: InnoDB requires an index on every FK column; declaring it
    # explicitly keeps model metadata in parity with the MySQL schema
    actor_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    detail = Column(Text, nullable=True)  # JSON payload or free-text note

    __table_args__ = (
        Index("idx_support_ticket_events_ticket", ticket_id, "created_at"),
    )

    def __repr__(self):
        return f"<SupportTicketEvent(id={self.id}, ticket_id={self.ticket_id}, event_type={self.event_type})>"
