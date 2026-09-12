# app/modules/support/router.py
"""
Support tickets router — create/requester views + platform_admin pickup.

Ticket creation accepts authenticated and anonymous requests (anonymous
requires a contact email and relies on the global per-IP rate limiter).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_active_user, to_uuid
from app.db.session import get_db
from app.models.user import User, UserStatus
from app.modules.support.service.base import SupportService
from app.modules.support.service.dependency import get_support_service
from app.schemas.support import (
    SupportTicketAdminUpdate,
    SupportTicketCreate,
    SupportTicketEventResponse,
    SupportTicketResponse,
)
from fastapi.security import OAuth2PasswordBearer

router = APIRouter()

get_db_depends = Depends(get_db)
get_support_service_depends = Depends(get_support_service)

# Non-fatal bearer scheme: missing header → anonymous (401 is NOT raised).
optional_oauth2 = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)
optional_oauth2_depends = Depends(optional_oauth2)


async def get_optional_current_user(
    token: Optional[str] = optional_oauth2_depends,
    db: AsyncSession = get_db_depends,
) -> Optional[User]:
    """Like get_current_active_user, but returns None for anonymous requests.

    A missing header yields an anonymous session; a malformed/expired token
    value also yields anonymous (rate limiting still applies per IP).
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = payload.get("sub")
        if isinstance(user_id, dict):
            user_id = user_id.get("id")
        target = to_uuid(user_id)
    except (JWTError, ValueError):
        return None
    result = await db.execute(select(User).where(User.id == target))
    user = result.scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE:
        return None
    return user

def _require_platform_admin(current_user) -> None:
    if getattr(current_user.role, "value", current_user.role) != "platform_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only platform admins can manage support tickets")


@router.post("/tickets", response_model=SupportTicketResponse, status_code=201)
async def create_ticket(
    data: SupportTicketCreate,
    current_user: Optional[User] = Depends(get_optional_current_user),
    service: SupportService = Depends(get_support_service),
):
    """Create a support ticket. Authenticated users get requester attribution;
    anonymous requests must provide a contact_email (rate limited per IP)."""
    return await service.create_ticket(
        data,
        requester_user_id=current_user.id if current_user else None,
        actor="requester" if current_user else "agent",
    )


@router.get("/tickets/mine", response_model=list[SupportTicketResponse])
async def list_my_tickets(
    current_user=Depends(get_current_active_user),
    service: SupportService = Depends(get_support_service),
    skip: int = 0,
    limit: int = Query(50, le=100),
):
    """List the current user's tickets."""
    return await service.list_mine(current_user.id, skip=skip, limit=limit)


@router.get("/tickets/{ticket_ref}", response_model=SupportTicketResponse)
async def get_ticket(
    ticket_ref: str,
    current_user: Optional[User] = Depends(get_optional_current_user),
    service: SupportService = Depends(get_support_service),
):
    """Get a ticket. Requester sees own; admins see all; anonymous only via number (no PII scoping possible)."""
    ticket = await service.get_ticket(ticket_ref)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    if current_user is None:
        # Anonymous access only allowed via exact ticket number (unguessable ref)
        if ticket.ticket_number != ticket_ref:
            raise HTTPException(status_code=403, detail="Not authorized to view this ticket")
        return ticket
    role = getattr(current_user.role, "value", current_user.role)
    if role == "platform_admin" or ticket.requester_user_id == current_user.id:
        return ticket
    raise HTTPException(status_code=403, detail="Not authorized to view this ticket")


@router.get("/tickets/{ticket_ref}/events", response_model=list[SupportTicketEventResponse])
async def list_ticket_events(
    ticket_ref: str,
    current_user=Depends(get_current_active_user),
    service: SupportService = Depends(get_support_service),
):
    """Audit trail. Requester or platform_admin only."""
    ticket = await service.get_ticket(ticket_ref)
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    role = getattr(current_user.role, "value", current_user.role)
    if role != "platform_admin" and ticket.requester_user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this ticket's events")
    return await service.list_events(ticket_ref)


# ── Admin (human pickup) ─────────────────────────────────────────────────
@router.get("/admin/tickets", response_model=list[SupportTicketResponse])
async def admin_list_tickets(
    current_user=Depends(get_current_active_user),
    service: SupportService = Depends(get_support_service),
    status_filter: str | None = Query(None, alias="status"),
    category: str | None = None,
    priority: str | None = None,
    skip: int = 0,
    limit: int = Query(100, le=200),
):
    """Ticket queue for humans. platform_admin only."""
    _require_platform_admin(current_user)
    return await service.list_tickets(status=status_filter, category=category, priority=priority, skip=skip, limit=limit)


@router.patch("/admin/tickets/{ticket_ref}", response_model=SupportTicketResponse)
async def admin_update_ticket(
    ticket_ref: str,
    data: SupportTicketAdminUpdate,
    current_user=Depends(get_current_active_user),
    service: SupportService = Depends(get_support_service),
):
    """Assign / transition status / add notes. platform_admin only."""
    _require_platform_admin(current_user)
    return await service.admin_update(ticket_ref, data, current_user.id)


def get_router():
    return router

