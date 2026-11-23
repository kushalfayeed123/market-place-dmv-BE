# app/modules/links/service/base.py
"""
Abstract base class for the share-link service.
"""

from abc import ABC, abstractmethod

from app.schemas.share_link import ShareLinkCreate, ShareLinkResolveResponse, ShareLinkResponse


class ShareLinkService(ABC):
    """Contract for share-link operations."""

    @abstractmethod
    async def create_link(
        self, merchant_id: str, data: ShareLinkCreate
    ) -> ShareLinkResponse:
        """Create a store or product-set share link owned by ``merchant_id``."""
        ...

    @abstractmethod
    async def list_links(
        self, merchant_id: str, skip: int = 0, limit: int = 100
    ) -> list[ShareLinkResponse]:
        """List share links belonging to a merchant."""
        ...

    @abstractmethod
    async def get_link(self, link_id: str, merchant_id: str) -> ShareLinkResponse | None:
        """Get one of a merchant's links by id (None when not found / not owned)."""
        ...

    @abstractmethod
    async def deactivate_link(self, link_id: str, merchant_id: str) -> ShareLinkResponse | None:
        """Disable a link so it no longer resolves publicly."""
        ...

    @abstractmethod
    async def resolve_public(self, code: str) -> ShareLinkResolveResponse | None:
        """Public resolution of a link code: store info plus the products it exposes."""
        ...
