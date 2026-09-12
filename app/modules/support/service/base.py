# app/modules/support/service/base.py
"""Abstract interface for the support ticket service."""

from abc import ABC, abstractmethod

from app.schemas.support import (
    SupportTicketAdminUpdate,
    SupportTicketCreate,
    SupportTicketEventResponse,
    SupportTicketResponse,
)


class SupportService(ABC):
    """Contract for support ticket operations."""

    @abstractmethod
    async def create_ticket(
        self, data: SupportTicketCreate,
        *, requester_user_id=None, actor: str = "requester",
    ) -> SupportTicketResponse: ...

    @abstractmethod
    async def list_mine(self, requester_user_id, skip: int = 0, limit: int = 50) -> list[SupportTicketResponse]: ...

    @abstractmethod
    async def get_ticket(self, ticket_ref: str) -> SupportTicketResponse | None:
        """Resolve by ticket_number first, then by UUID id."""

    @abstractmethod
    async def list_tickets(
        self, *, status: str | None = None, category: str | None = None,
        priority: str | None = None, skip: int = 0, limit: int = 100,
    ) -> list[SupportTicketResponse]: ...

    @abstractmethod
    async def admin_update(self, ticket_ref: str, data: SupportTicketAdminUpdate, admin_user_id) -> SupportTicketResponse: ...

    @abstractmethod
    async def list_events(self, ticket_ref: str) -> list[SupportTicketEventResponse]: ...
