# app/modules/support/service/implementation.py
"""Database-backed support ticket service.

Ticket creation is transactional: ticket + initial event + notification
webhook_events row commit together, so a notification can never be lost.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import to_uuid
from app.models.support_ticket import (
    SupportTicket,
    SupportTicketEvent,
    TicketCategory,
    TicketEventActor,
    TicketPriority,
    TicketStatus,
)
from app.models.webhook_event import WebhookEvent
from app.schemas.support import (
    SupportTicketAdminUpdate,
    SupportTicketCreate,
    SupportTicketEventResponse,
    SupportTicketResponse,
)
from app.modules.support.service.base import SupportService

_TICKET_NUMBER_FMT = "TCK-{date}-{token}"
_REQUESTER_VISIBLE_STATUSES = {"resolved", "closed"}


def _ticket_number() -> str:
    date = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _TICKET_NUMBER_FMT.format(date=date, token=uuid.uuid4().hex[:8])


def _to_response(t: SupportTicket) -> SupportTicketResponse:
    return SupportTicketResponse(
        id=str(t.id), ticket_number=t.ticket_number, status=t.status.value,
        priority=t.priority.value, category=t.category.value, subject=t.subject,
        description=t.description, requester_user_id=str(t.requester_user_id) if t.requester_user_id else None,
        contact_email=t.contact_email, order_id=str(t.order_id) if t.order_id else None,
        payment_id=str(t.payment_id) if t.payment_id else None,
        merchant_id=str(t.merchant_id) if t.merchant_id else None,
        session_id=t.session_id, correlation_id=t.correlation_id,
        assigned_to=str(t.assigned_to) if t.assigned_to else None,
        resolution_notes=t.resolution_notes, created_at=t.created_at, updated_at=t.updated_at,
    )


class SupportServiceImpl(SupportService):
    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_ticket(
        self, data: SupportTicketCreate, *, requester_user_id=None, actor: str = "requester",
    ) -> SupportTicketResponse:
        # Business rule: anonymous tickets must carry a contact email.
        if requester_user_id is None and not (data.contact_email and "@" in data.contact_email):
            raise HTTPException(
                status_code=422,
                detail="contact_email is required when creating a ticket without signing in",
            )
        ticket = SupportTicket(
            ticket_number=_ticket_number(),
            status=TicketStatus.NEW,
            priority=TicketPriority(data.priority.value),
            category=TicketCategory(data.category.value),
            subject=data.subject,
            description=data.description,
            requester_user_id=to_uuid(requester_user_id) if requester_user_id else None,
            contact_email=data.contact_email,
            order_id=_safe_uuid(data.order_id),
            payment_id=_safe_uuid(data.payment_id),
            merchant_id=_safe_uuid(data.merchant_id),
            session_id=data.session_id,
            correlation_id=data.correlation_id,
        )
        event = SupportTicketEvent(
            ticket_id=ticket.id,
            event_type="created",
            actor=TicketEventActor(actor),
            actor_user_id=to_uuid(requester_user_id) if requester_user_id else None,
            detail=json.dumps({"subject": data.subject, "category": data.category.value}),
        )
        notification = WebhookEvent(
            provider="support",
            event_id=f"support.ticket.created:{ticket.id}",
            event_type="support.ticket.created",
            payload=json.dumps(_notification_payload(ticket), default=str),
        )
        self._db.add_all([ticket, event, notification])
        await self._db.commit()
        await self._db.refresh(ticket)
        return _to_response(ticket)

    async def list_mine(self, requester_user_id, skip: int = 0, limit: int = 50) -> list[SupportTicketResponse]:
        result = await self._db.execute(
            select(SupportTicket)
            .where(SupportTicket.requester_user_id == to_uuid(requester_user_id))
            .order_by(SupportTicket.created_at.desc())
            .offset(skip).limit(limit)
        )
        return [_to_response(t) for t in result.scalars().all()]

    async def get_ticket(self, ticket_ref: str) -> SupportTicketResponse | None:
        ticket = await self._resolve(ticket_ref)
        return _to_response(ticket) if ticket else None

    async def list_tickets(
        self, *, status: str | None = None, category: str | None = None,
        priority: str | None = None, skip: int = 0, limit: int = 100,
    ) -> list[SupportTicketResponse]:
        query = select(SupportTicket).order_by(SupportTicket.created_at.desc())
        if status:
            query = query.where(SupportTicket.status == TicketStatus(status))
        if category:
            query = query.where(SupportTicket.category == TicketCategory(category))
        if priority:
            query = query.where(SupportTicket.priority == TicketPriority(priority))
        result = await self._db.execute(query.offset(skip).limit(limit))
        return [_to_response(t) for t in result.scalars().all()]

    async def admin_update(
        self, ticket_ref: str, data: SupportTicketAdminUpdate, admin_user_id,
    ) -> SupportTicketResponse:
        ticket = await self._resolve(ticket_ref)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Support ticket not found")

        events: list[SupportTicketEvent] = []
        updates = data.model_dump(exclude_unset=True)
        if "status" in updates and updates["status"] is not None:
            new_status = TicketStatus(updates["status"])
            if new_status != ticket.status:
                events.append(SupportTicketEvent(
                    ticket_id=ticket.id, event_type="status_changed",
                    actor=TicketEventActor.ADMIN, actor_user_id=to_uuid(admin_user_id),
                    detail=json.dumps({"from": ticket.status.value, "to": new_status.value}),
                ))
                ticket.status = new_status
                # Notify the requester on human-visible outcome transitions.
                if new_status.value in _REQUESTER_VISIBLE_STATUSES:
                    self._db.add(WebhookEvent(
                        provider="support",
                        event_id=f"support.ticket.status:{ticket.id}:{new_status.value}",
                        event_type="support.ticket.status_changed",
                        payload=json.dumps(_notification_payload(ticket), default=str),
                    ))
        if "priority" in updates and updates["priority"] is not None:
            ticket.priority = TicketPriority(updates["priority"])
        if "assigned_to" in updates and updates["assigned_to"] is not None:
            new_assignee = to_uuid(updates["assigned_to"])
            if new_assignee != ticket.assigned_to:
                events.append(SupportTicketEvent(
                    ticket_id=ticket.id, event_type="assigned",
                    actor=TicketEventActor.ADMIN, actor_user_id=to_uuid(admin_user_id),
                    detail=json.dumps({"assigned_to": str(new_assignee)}),
                ))
                ticket.assigned_to = new_assignee
        if "resolution_notes" in updates and updates["resolution_notes"] is not None:
            ticket.resolution_notes = updates["resolution_notes"]

        self._db.add_all(events)
        await self._db.commit()
        await self._db.refresh(ticket)
        return _to_response(ticket)

    async def list_events(self, ticket_ref: str) -> list[SupportTicketEventResponse]:
        ticket = await self._resolve(ticket_ref)
        if ticket is None:
            raise HTTPException(status_code=404, detail="Support ticket not found")
        result = await self._db.execute(
            select(SupportTicketEvent)
            .where(SupportTicketEvent.ticket_id == ticket.id)
            .order_by(SupportTicketEvent.created_at.asc())
        )
        return [SupportTicketEventResponse(
            id=str(e.id), ticket_id=str(e.ticket_id), event_type=e.event_type,
            actor=e.actor.value, detail=e.detail, created_at=e.created_at,
        ) for e in result.scalars().all()]

    async def _resolve(self, ticket_ref: str) -> SupportTicket | None:
        result = await self._db.execute(
            select(SupportTicket).where(SupportTicket.ticket_number == ticket_ref)
        )
        ticket = result.scalar_one_or_none()
        if ticket is None and _looks_like_uuid(ticket_ref):
            ticket = await self._db.get(SupportTicket, to_uuid(ticket_ref))
        return ticket


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _safe_uuid(value: str | None):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


def _notification_payload(ticket: SupportTicket) -> dict:
    return {
        "ticket_number": ticket.ticket_number,
        "ticket_id": str(ticket.id),
        "status": ticket.status.value,
        "priority": ticket.priority.value,
        "category": ticket.category.value,
        "subject": ticket.subject,
        "requester_user_id": str(ticket.requester_user_id) if ticket.requester_user_id else None,
        "contact_email": ticket.contact_email,
        "order_id": str(ticket.order_id) if ticket.order_id else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

