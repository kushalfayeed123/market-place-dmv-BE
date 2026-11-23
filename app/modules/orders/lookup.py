# app/modules/orders/lookup.py
"""Resolve an order reference that may be either its UUID id or its
human-readable order number (e.g. ``ORD-20261109-190345-17ec``).

Buyers and the agent routinely reference orders by order number, so every
buyer-facing lookup should accept both forms instead of crashing on
``to_uuid`` with a 500.
"""

from __future__ import annotations

from app.core.security import to_uuid
from app.models.order import Order
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_order_by_ref(db: AsyncSession, ref: str) -> Order | None:
    """Return the order matching a UUID id or an order number, else None."""
    try:
        oid = to_uuid(ref)
    except ValueError:
        oid = None
    if oid is not None:
        result = await db.execute(select(Order).where(Order.id == oid))
    else:
        result = await db.execute(select(Order).where(Order.order_number == ref))
    return result.scalar_one_or_none()
