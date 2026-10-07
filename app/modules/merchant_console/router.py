# backend/app/modules/merchant_console/router.py
"""
Merchant-console router.

Provides the endpoints the frontend merchant dashboard expects:
  • Merchant-scoped *list* endpoints:
      GET  /merchants/{id}/orders
      GET  /merchants/{id}/products
      GET  /merchants/{id}/shipments  (fulfillments)
      GET  /merchants/{id}/payouts
      GET  /merchants/{id}/disputes
      GET  /merchants/{id}/conversations
      GET  /merchants/{id}/attention   (dashboard counts)
  • Resource *action* endpoints (non-merchant-scoped — ownership is
    verified server-side by looking up the resource):
      POST   /orders/{id}/accept|ship|cancel
      POST   /products/{id}/publish|unpublish
      DELETE /products/{id}
      POST   /shipments/{id}/pickup
      POST   /shipments/{id}/delivered
      POST   /payouts/{id}/cancel
      POST   /disputes/{id}/accept
      POST   /disputes/{id}/evidence
      POST   /conversations/{id}/resolve

All endpoints require an authenticated user.  Merchant-scoped endpoints
verify ownership; resource actions verify ownership via the resource's
merchant FK.
"""

import uuid
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user, to_uuid
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.dispute import Dispute
from app.models.fulfillment import Fulfillment
from app.models.inventory import Inventory
from app.models.merchant import Merchant
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.payout import Payout
from app.models.product import Product, ProductStatus
from app.models.product_variant import ProductVariant
from app.models.user import User, UserRole
from app.schemas.merchant_console import (
    AttentionResponse,
    ConversationListItem,
    DisputeListItem,
    MerchantOrderListItem,
    MerchantProductListItem,
    MerchantShipmentListItem,
    PayoutListItem,
)
from app.schemas.merchants import KycReviewRequest, PayoutCreate, PayoutResponse

router = APIRouter()

# ── Dependencies ─────────────────────────────────────────────────────────

get_current_active_user_depends = Depends(get_current_active_user)
get_db_depends = Depends(get_db)



# ── Authorization helpers ────────────────────────────────────────────────


async def _require_merchant_access(
    merchant_id: str,
    current_user: User,
    db: AsyncSession,
) -> Merchant:
    """Fetch a merchant and verify the current user owns it."""
    merchant = await db.get(Merchant, to_uuid(merchant_id))
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Merchant not found",
        )
    if current_user.role == UserRole.PLATFORM_ADMIN:
        return merchant
    if merchant.owner_user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this merchant",
        )
    return merchant


# ── Attention / overview ──────────────────────────────────────────────────

@router.get(
    "/merchants/{merchant_id}/attention",
    response_model=AttentionResponse,
)
async def get_merchant_attention(
    merchant_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Return counts of items needing the merchant's attention."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    orders_to_fulfil = await db.scalar(
        select(func.count())
        .select_from(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.merchant_id == mid)
        .where(Order.status.in_([
            OrderStatus.PAID.value,
            OrderStatus.PARTIALLY_FULFILLED.value,
        ]))
    )

    disputes_due = await db.scalar(
        select(func.count())
        .select_from(Dispute)
        .where(Dispute.merchant_id == mid)
        .where(Dispute.status == "open")
        .where(Dispute.respond_by > func.now())
    )

    unread_messages = await db.scalar(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.merchant_id == mid)
        .where(Conversation.status == "unread")
    )

    low_stock = await db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.merchant_id == mid)
        .where(
            ~select(ProductVariant.id)
            .where(ProductVariant.product_id == Product.id)
            .exists()
        )
    )

    low_stock_by_inv = await db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.merchant_id == mid)
        .where(
            select(func.coalesce(func.sum(Inventory.quantity_available), 0))
            .where(
                Inventory.variant_id.in_(
                    select(ProductVariant.id)
                    .where(ProductVariant.product_id == Product.id)
                )
            )
            .scalar_subquery()
            <= 0
        )
    )

    return AttentionResponse(
        orders_to_fulfil=orders_to_fulfil or 0,
        disputes_due=disputes_due or 0,
        unread_messages=unread_messages or 0,
                low_stock=(low_stock or 0) + (low_stock_by_inv or 0),
    )


# ── Merchant-scoped list endpoints ──────────────────────────────────────

@router.get(
    "/merchants/{merchant_id}/orders",
    response_model=list[MerchantOrderListItem],
)
async def list_merchant_orders(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List orders that contain items for this merchant."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    q = (
        select(Order, OrderItem)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(OrderItem.merchant_id == mid)
    )
    if status:
        q = q.where(Order.status == status)
    if search:
        q = q.where(Order.order_number.ilike(f"%{search}%"))
    q = q.distinct().order_by(Order.created_at.desc()).limit(limit)
    result = await db.execute(q)
    rows = result.all()

    buyer_ids = [r.Order.buyer_id for r in rows]
    user_map: dict[str, str] = {}
    if buyer_ids:
        users = await db.execute(
            select(User.id, User.first_name, User.last_name, User.email)
            .where(User.id.in_(buyer_ids))
        )
        for u in users:
            name = f"{u.first_name or ''} {u.last_name or ''}".strip()
            if not name:
                name = (u.email or "").split("@")[0]
            user_map[str(u.id)] = name

    return [
        MerchantOrderListItem(
            id=str(r.Order.id),
            number=r.Order.order_number,
            customer_name=user_map.get(str(r.Order.buyer_id), ""),
            created_at=r.Order.created_at,
            total=r.Order.total_amount,
            currency=r.Order.currency,
            status=r.Order.status,
        )
        for r in rows
    ]


@router.get(
    "/merchants/{merchant_id}/products",
    response_model=list[MerchantProductListItem],
)
async def list_merchant_products(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List products for this merchant with first variant's SKU + stock."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    q = (
        select(Product)
        .where(Product.merchant_id == mid)
        .order_by(Product.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Product.status == status)
    if search:
        q = q.where(
            func.lower(Product.title).like(f"%{search.lower()}%")
            | func.lower(Product.slug).like(f"%{search.lower()}%")
        )
    products = (await db.execute(q)).scalars().all()

    pids = [p.id for p in products]
    variants = (
        await db.execute(
            select(ProductVariant)
            .where(ProductVariant.product_id.in_(pids))
            .order_by(ProductVariant.product_id, ProductVariant.created_at)
        )
    ).scalars().all()

    first_variant: dict[str, ProductVariant] = {}
    for v in variants:
        pid = str(v.product_id)
        if pid not in first_variant:
            first_variant[pid] = v

    inv_res = await db.execute(
        select(Inventory.variant_id, func.coalesce(func.sum(Inventory.quantity_available), 0).label("qty"))
        .where(Inventory.variant_id.in_([v.id for v in variants]))
        .group_by(Inventory.variant_id)
    )
    inv_map: dict[str, int] = {str(r.variant_id): r.qty for r in inv_res}

    return [
        MerchantProductListItem(
            id=str(p.id),
            title=p.title,
            sku=first_variant.get(str(p.id), ProductVariant(sku="")).sku if str(p.id) in first_variant else "",
            stock=int(
                inv_map.get(
                    str(first_variant[str(p.id)].id) if str(p.id) in first_variant else "missing",
                    0,
                )
            ) if str(p.id) in first_variant else 0,
            price=p.base_price_amount,
            currency=p.base_price_currency,
            status=p.status,
        )
                for p in products
    ]


@router.get(
    "/merchants/{merchant_id}/shipments",
    response_model=list[MerchantShipmentListItem],
)
async def list_merchant_shipments(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List fulfillments (shipments) for this merchant."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    q = (
        select(Fulfillment)
        .where(Fulfillment.merchant_id == mid)
        .order_by(Fulfillment.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Fulfillment.status == status)
    fulfillments = (await db.execute(q)).scalars().all()

    order_ids = [f.order_id for f in fulfillments if f.order_id]
    order_map: dict[str, str] = {}
    if order_ids:
        orders = await db.execute(
            select(Order.id, Order.order_number).where(Order.id.in_(order_ids))
        )
        for o in orders:
            order_map[str(o.id)] = o.order_number

    return [
        MerchantShipmentListItem(
            id=str(f.id),
            order_number=order_map.get(str(f.order_id), "—") if f.order_id else "—",
            courier=f.carrier,
            tracking_code=f.tracking_number,
            updated_at=f.updated_at,
            status=f.status,
        )
        for f in fulfillments
    ]


@router.get(
    "/merchants/{merchant_id}/payouts",
    response_model=list[PayoutListItem],
)
async def list_merchant_payouts(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List payout requests for this merchant."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = to_uuid(merchant.id)

    q = (
        select(Payout)
        .where(Payout.merchant_id == mid)
        .order_by(Payout.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Payout.status == status)
    payouts = (await db.execute(q)).scalars().all()

    return [
        PayoutListItem(
            id=str(p.id),
            reference=p.reference,
            bank_account=f"•••• {p.bank_account_last4}" if p.bank_account_last4 else p.bank_name,
            created_at=p.created_at,
            amount=p.amount,
            currency=p.currency,
            status=p.status,
        )
        for p in payouts
    ]


@router.get(
    "/merchants/{merchant_id}/disputes",
    response_model=list[DisputeListItem],
)
async def list_merchant_disputes(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List disputes for this merchant."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    q = (
        select(Dispute)
        .where(Dispute.merchant_id == mid)
        .order_by(Dispute.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Dispute.status == status)
    disputes = (await db.execute(q)).scalars().all()

    return [
        DisputeListItem(
            id=str(d.id),
            order_number=d.order_number,
            reason=d.reason,
            respond_by=d.respond_by,
            amount=d.amount,
            currency=d.currency,
            status=d.status,
        )
        for d in disputes
    ]


@router.get(
    "/merchants/{merchant_id}/conversations",
    response_model=list[ConversationListItem],
)
async def list_merchant_conversations(
    merchant_id: str,
    search: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, le=1000),
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """List conversations for this merchant."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)
    mid = merchant.id

    q = (
        select(Conversation)
        .where(Conversation.merchant_id == mid)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(Conversation.status == status)
    if search:
        q = q.where(
            func.lower(Conversation.customer_name).like(f"%{search.lower()}%")
            | func.lower(Conversation.last_message).like(f"%{search.lower()}%")
        )
    conversations = (await db.execute(q)).scalars().all()

    return [
        ConversationListItem(
            id=str(c.id),
            customer_name=c.customer_name,
            last_message=c.last_message,
            updated_at=c.updated_at,
            status=c.status,
        )
                for c in conversations
    ]


# ── Order actions ────────────────────────────────────────────────────────

async def _check_order_ownership(
    order_id: str, current_user: User, db: AsyncSession
) -> bool:
    """Return True if current_user owns a merchant that has items in this order."""
    if current_user.role == UserRole.PLATFORM_ADMIN:
        return True
    subquery = select(Merchant.id).where(Merchant.owner_user_id == current_user.id)
    result = await db.scalar(
        select(func.count())
        .select_from(OrderItem)
        .where(OrderItem.order_id == to_uuid(order_id))
        .where(OrderItem.merchant_id.in_(subquery))
    )
    return bool(result)


@router.post("/orders/{order_id}/accept")
async def accept_order(
    order_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Accept an order — transitions paid → partially_fulfilled."""
    if not await _check_order_ownership(order_id, current_user, db):
        raise HTTPException(status_code=403, detail="Not authorized to manage this order")
    order = await db.get(Order, to_uuid(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status != OrderStatus.PAID.value:
        raise HTTPException(status_code=400, detail=f"Order cannot be accepted from status '{order.status}'")
    order.status = OrderStatus.PARTIALLY_FULFILLED.value
    await db.commit()
    await db.refresh(order)
    return {"ok": True, "order_id": order_id, "status": order.status}


@router.post("/orders/{order_id}/ship")
async def ship_order(
    order_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Mark an order as shipped — transitions to fulfilled."""
    if not await _check_order_ownership(order_id, current_user, db):
        raise HTTPException(status_code=403, detail="Not authorized to manage this order")
    order = await db.get(Order, to_uuid(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in (OrderStatus.PARTIALLY_FULFILLED.value, OrderStatus.PAID.value):
        raise HTTPException(status_code=400, detail=f"Order cannot be shipped from status '{order.status}'")
    order.status = OrderStatus.FULFILLED.value
    await db.commit()
    await db.refresh(order)
    return {"ok": True, "order_id": order_id, "status": order.status}


@router.post("/orders/{order_id}/cancel")
async def cancel_order(
    order_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Cancel an order — transitions to cancelled."""
    if not await _check_order_ownership(order_id, current_user, db):
        raise HTTPException(status_code=403, detail="Not authorized to manage this order")
    order = await db.get(Order, to_uuid(order_id))
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in (OrderStatus.PAID.value, OrderStatus.PARTIALLY_FULFILLED.value):
        raise HTTPException(status_code=400, detail=f"Order cannot be cancelled from status '{order.status}'")
    order.status = OrderStatus.CANCELLED.value
    await db.commit()
    await db.refresh(order)
    return {"ok": True, "order_id": order_id, "status": order.status}


# ── Product actions ──────────────────────────────────────────────────────

async def _get_owned_merchant_ids(current_user: User, db: AsyncSession) -> list:
    """Return all merchant IDs owned by the current user (or all for admin)."""
    if current_user.role == UserRole.PLATFORM_ADMIN:
        return [r for r in (await db.scalars(select(Merchant.id))).all()]
    return [r for r in (await db.scalars(
        select(Merchant.id).where(Merchant.owner_user_id == current_user.id)
    )).all()]


# ── Product actions ──────────────────────────────────────────────────────

@router.post("/products/{product_id}/publish")
async def publish_product(
    product_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Publish a product — draft → active."""
    product = await db.get(Product, to_uuid(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if product.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if product.status != ProductStatus.DRAFT.value:
        raise HTTPException(status_code=400, detail=f"Product cannot be published from status '{product.status}'")
    product.status = ProductStatus.ACTIVE.value
    await db.commit()
    await db.refresh(product)
    return {"ok": True, "product_id": product_id, "status": product.status}


@router.post("/products/{product_id}/unpublish")
async def unpublish_product(
    product_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Unpublish a product — active → draft."""
    product = await db.get(Product, to_uuid(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if product.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if product.status != ProductStatus.ACTIVE.value:
        raise HTTPException(status_code=400, detail=f"Product cannot be unpublished from status '{product.status}'")
    product.status = ProductStatus.DRAFT.value
    await db.commit()
    await db.refresh(product)
    return {"ok": True, "product_id": product_id, "status": product.status}


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Delete a product."""
    product = await db.get(Product, to_uuid(product_id))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if product.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    await db.delete(product)
    await db.commit()
    return {"ok": True, "product_id": product_id}


# ── Shipment (fulfillment) actions ──────────────────────────────────────

@router.post("/shipments/{shipment_id}/pickup")
async def request_pickup(
    shipment_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Request pickup — pending → shipped."""
    fulfillment = await db.get(Fulfillment, to_uuid(shipment_id))
    if not fulfillment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if fulfillment.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if fulfillment.status != "pending":
        raise HTTPException(status_code=400, detail=f"Cannot request pickup from status '{fulfillment.status}'")
    fulfillment.status = "shipped"
    await db.commit()
    await db.refresh(fulfillment)
    return {"ok": True, "shipment_id": shipment_id, "status": fulfillment.status}


@router.post("/shipments/{shipment_id}/delivered")
async def mark_delivered(
    shipment_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Mark a shipment as delivered."""
    fulfillment = await db.get(Fulfillment, to_uuid(shipment_id))
    if not fulfillment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if fulfillment.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if fulfillment.status not in ("pending", "shipped"):
        raise HTTPException(status_code=400, detail=f"Cannot mark delivered from status '{fulfillment.status}'")
    from app.models.enums import FulfillmentStatus as FS
    fulfillment.status = FS.DELIVERED.value
    fulfillment.delivered_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(fulfillment)
    return {"ok": True, "shipment_id": shipment_id, "status": fulfillment.status}


# ── Payout actions ───────────────────────────────────────────────────────

@router.post("/payouts/{payout_id}/cancel")
async def cancel_payout(
    payout_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Cancel a payout request — only if still 'requested'."""
    payout = await db.get(Payout, to_uuid(payout_id))
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if payout.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if payout.status != "requested":
        raise HTTPException(status_code=400, detail=f"Cannot cancel payout from status '{payout.status}'")
    payout.status = "cancelled"
    await db.commit()
    await db.refresh(payout)
    return {"ok": True, "payout_id": payout_id, "status": payout.status}


# ── Payout requests ──────────────────────────────────────────────────────

@router.post(
    "/merchants/{merchant_id}/payouts",
    response_model=PayoutResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_payout_request(
    merchant_id: str,
    payout_data: PayoutCreate,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Create a payout request for a merchant (withdraw funds)."""
    merchant = await _require_merchant_access(merchant_id, current_user, db)

    # Must have an active payout account
    from app.models.merchant_payout_account import MerchantPayoutAccount
    result = await db.execute(
        select(MerchantPayoutAccount).where(
            MerchantPayoutAccount.merchant_id == merchant.id,
            MerchantPayoutAccount.is_active.is_(True),
        )
    )
    account = result.scalar_one_or_none()
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active payout account found. Set up a payout account first.",
        )

    reference = f"pout_{uuid4().hex[:12]}"
    new_payout = Payout(
        merchant_id=merchant.id,
        amount=payout_data.amount,
        currency=payout_data.currency,
        status="requested",
        reference=reference,
        bank_account_last4=account.account_last4,
        bank_name=account.bank_name,
    )
    db.add(new_payout)
    await db.commit()
    await db.refresh(new_payout)

    return PayoutResponse(
        id=str(new_payout.id),
        merchant_id=str(new_payout.merchant_id),
        amount=new_payout.amount,
        currency=new_payout.currency,
        status=new_payout.status,
        reference=new_payout.reference,
        bank_account_last4=new_payout.bank_account_last4,
        bank_name=new_payout.bank_name,
        requested_at=new_payout.requested_at,
        processed_at=new_payout.processed_at,
        paid_at=new_payout.paid_at,
        created_at=new_payout.created_at,
        updated_at=new_payout.updated_at,
    )


# ── Admin KYC review ────────────────────────────────────────────────────

@router.patch(
    "/admin/merchants/{merchant_id}/kyc",
    response_model=dict[str, Any],
)
async def review_merchant_kyc(
    merchant_id: str,
    kyc_data: KycReviewRequest,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Admin-only: review a merchant's KYC status."""
    if current_user.role != UserRole.PLATFORM_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins can review KYC",
        )
    merchant = await db.get(Merchant, to_uuid(merchant_id))
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Merchant not found",
        )
    merchant.kyc_status = kyc_data.kyc_status
    if kyc_data.reason:
        merchant.kyc_provider_ref = (merchant.kyc_provider_ref or "") + f" | {kyc_data.reason}"
    await db.commit()
    await db.refresh(merchant)
    return {
        "merchant_id": str(merchant.id),
        "kyc_status": merchant.kyc_status,
        "reason": kyc_data.reason,
    }


# ── Dispute actions ──────────────────────────────────────────────────────

@router.post("/disputes/{dispute_id}/accept")
async def accept_dispute(
    dispute_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Accept a dispute — merchant loses."""
    dispute = await db.get(Dispute, to_uuid(dispute_id))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if dispute.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if dispute.status != "open":
        raise HTTPException(status_code=400, detail=f"Cannot accept dispute from status '{dispute.status}'")
    dispute.status = "lost"
    await db.commit()
    await db.refresh(dispute)
    return {"ok": True, "dispute_id": dispute_id, "status": dispute.status}


@router.post("/disputes/{dispute_id}/evidence")
async def submit_evidence(
    dispute_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Submit evidence for a dispute — open → evidence_submitted."""
    dispute = await db.get(Dispute, to_uuid(dispute_id))
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if dispute.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    if dispute.status != "open":
        raise HTTPException(status_code=400, detail=f"Cannot submit evidence from status '{dispute.status}'")
    dispute.status = "evidence_submitted"
    await db.commit()
    await db.refresh(dispute)
    return {"ok": True, "dispute_id": dispute_id, "status": dispute.status}


# ── Conversation actions ───────────────────────────────────────────────────

@router.post("/conversations/{conversation_id}/resolve")
async def resolve_conversation(
    conversation_id: str,
    current_user: User = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Mark a conversation as resolved."""
    conv = await db.get(Conversation, to_uuid(conversation_id))
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    owned = await _get_owned_merchant_ids(current_user, db)
    if conv.merchant_id not in owned:
        raise HTTPException(status_code=403, detail="Not authorized")
    conv.status = "resolved"
    await db.commit()
    await db.refresh(conv)
    return {"ok": True, "conversation_id": conversation_id, "status": conv.status}


def get_router():
    return router


