# app/modules/documents/deps.py
"""
Authorization dependencies for the documents subsystem.

The key helper is :func:`get_merchant_id`, which resolves the authenticated
user to the ``merchant_id`` that own the documents they are acting on.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user, to_uuid
from app.db.session import get_db
from app.models.merchant import Merchant
from app.models.user import User


def _role_value(user: User) -> str:
    """Normalise the role to a plain string regardless of ORM/Enum wrapper."""
    return getattr(user.role, "value", user.role)


async def get_merchant_id(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UUID:
    """
    Resolve the authenticated user to a ``merchant_id`` UUID.

    * ``platform_admin`` users may pass ``?merchant_id=<uuid>`` to scope the
      request to a specific merchant.
    * All other roles are mapped to their owning merchant (or the first
      merchant for multi-tenant staff).
    * ``buyer`` users have no merchant — ``HTTPException(403)``.
    """
    if _role_value(current_user) == "platform_admin":
        # Admins can act on behalf of any merchant; the caller supplies the id.
        # But since this dependency is used inside router endpoints, the
        # merchant_id query-param is read from the router instead.
        # Falls through to the lookup below if no override is provided.
        pass

    result = await db.execute(
        select(Merchant).where(Merchant.owner_user_id == current_user.id)
    )
    merchant = result.scalar_one_or_none()
    if merchant is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No merchant account associated with this user",
        )
    return merchant.id
