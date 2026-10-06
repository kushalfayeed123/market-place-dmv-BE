# app/modules/orders/service/implementation.py
"""
Concrete implementation of the order service.
Handles database operations for orders using SQLAlchemy.
"""


import uuid
from datetime import datetime, timezone

from app.core.security import to_uuid
from app.models.inventory import Inventory
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.modules.orders.service.base import OrderService
from app.schemas.orders import (
    CheckoutRequest,
    CheckoutResponse,
    OrderResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _generate_order_number() -> str:
    """Generate a human-readable, unique order number.

    Format: ORD-YYYYMMDD-HHMMSS-XXXX where XXXX is 4 hex chars from a UUID.
    Example: ORD-20261005-143022-8a3f
    """
    now = datetime.now(timezone.utc)
    return f"ORD-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}-{uuid.uuid4().hex[:4]}"


class OrderServiceImpl(OrderService):
    """
    Database-backed implementation of OrderService.
    
    This class encapsulates all database operations for orders,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.

        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def checkout(
        self, checkout_data: CheckoutRequest, buyer_id: str, idempotency_key: str
    ) -> CheckoutResponse:
        """
        Process checkout and create an order in the database.

        Args:
            checkout_data: The checkout request data.
            buyer_id: The buyer's user ID.
            idempotency_key: The idempotency key for the order.

        Returns:
            The checkout response with order details.

        Raises:
            ValueError: If cart items are invalid or inventory insufficient.
        """
        # Calculate order total and validate items
        order_total = 0
        order_items_data = []

        for cart_item in checkout_data.items:
            # Get product variant
            result = await self._db.execute(
                select(ProductVariant).where(
                    ProductVariant.id == to_uuid(cart_item.variant_id)
                )
            )
            variant = result.scalar_one_or_none()

            if not variant:
                raise ValueError(f"Product variant {cart_item.variant_id} not found")

            # Get product to verify merchant/store
            result = await self._db.execute(
                select(Product).where(Product.id == variant.product_id)
            )
            product = result.scalar_one_or_none()

            if not product:
                raise ValueError(f"Product for variant {cart_item.variant_id} not found")

            # Check inventory if tracked
            if variant.inventory_policy == "tracked":
                result = await self._db.execute(
                    select(Inventory).where(Inventory.variant_id == variant.id)
                )
                inventory = result.scalar_one_or_none()

                if not inventory or inventory.quantity_available < cart_item.quantity:
                    raise ValueError(
                        f"Insufficient inventory for variant {cart_item.variant_id}"
                    )

                # Reserve inventory
                inventory.quantity_available -= cart_item.quantity
                inventory.quantity_reserved += cart_item.quantity

            # Calculate price
            unit_price = variant.price_override_amount or product.base_price_amount
            currency = variant.price_override_currency or product.base_price_currency
            line_total = unit_price * cart_item.quantity
            order_total += line_total

            order_items_data.append({
                "product_id": product.id,
                "variant_id": variant.id,
                "merchant_id": product.merchant_id,
                "quantity": cart_item.quantity,
                "unit_price": unit_price,
                "currency": currency,
                "line_total": line_total,
            })

        # Create order
        new_order = Order(
            buyer_id=to_uuid(buyer_id),
            order_number=_generate_order_number(),
            status=OrderStatus.PENDING.value,
            currency=currency,
            total_amount=order_total,
            idempotency_key=idempotency_key,
        )

        self._db.add(new_order)
        await self._db.commit()
        await self._db.refresh(new_order)

        # Create order items
        for item_data in order_items_data:
            order_item = OrderItem(
                order_id=new_order.id,
                **item_data,
            )
            self._db.add(order_item)

        await self._db.commit()

        return CheckoutResponse(
            id=str(new_order.id),
            order_number=new_order.order_number,
            status=new_order.status,
            currency=new_order.currency,
            total_amount=new_order.total_amount,
            idempotency_key=new_order.idempotency_key,
            created_at=new_order.created_at,
            items=[
                {
                    "id": str(item_data.get("variant_id", "")),
                    "product_id": str(item_data["product_id"]),
                    "variant_id": str(item_data["variant_id"]) if item_data.get("variant_id") else None,
                    "merchant_id": str(item_data["merchant_id"]),
                    "quantity": item_data["quantity"],
                    "unit_price": item_data["unit_price"],
                    "currency": item_data["currency"],
                    "line_total": item_data["line_total"],
                }
                for item_data in order_items_data
            ],
        )

    async def get_order(
        self, order_id: str, merchant_id: str | None = None
    ) -> OrderResponse | None:
        """
        Get an order by ID with its items from the database.
        
        Args:
            order_id: The order ID.
            merchant_id: Filter order items by merchant (only return items belonging to this merchant).
            
        Returns:
            The order response if found, None otherwise.
        """
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(order_id))
        )
        order = result.scalar_one_or_none()

        if order is None:
            return None

        # Get order items
        query = select(OrderItem).where(OrderItem.order_id == order.id)
        
        # Filter by merchant if provided
        if merchant_id is not None:
            query = query.where(OrderItem.merchant_id == to_uuid(merchant_id))
            
        result = await self._db.execute(query)
        order_items = result.scalars().all()

        return OrderResponse(
            id=str(order.id),
            order_number=order.order_number,
            buyer_id=str(order.buyer_id),
            status=order.status,
            currency=order.currency,
            total_amount=order.total_amount,
            idempotency_key=order.idempotency_key,
            created_at=order.created_at,
            updated_at=order.updated_at,
            items=[
                {
                    "id": str(item.id),
                    "product_id": str(item.product_id),
                    "variant_id": str(item.variant_id) if item.variant_id else None,
                    "merchant_id": str(item.merchant_id),
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "currency": item.currency,
                    "line_total": item.line_total,
                }
                for item in order_items
            ],
        )

    async def list_orders(
        self,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
        merchant_id: str | None = None,
    ) -> list[OrderResponse]:
        """
        List orders with optional filtering from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            status: Filter by order status.
            user_id: Current user ID for access control.
            user_role: Current user role for access control.
            merchant_id: Filter orders by merchant (joins through OrderItem).
            
        Returns:
            List of order responses.
        """
        query = select(Order)

        # Filter by user role
        if user_role == "buyer":
            query = query.where(Order.buyer_id == to_uuid(user_id))

        # Filter by merchant - join through OrderItem
        if merchant_id is not None:
            query = query.join(OrderItem, OrderItem.order_id == Order.id).where(
                OrderItem.merchant_id == to_uuid(merchant_id)
            )

        if status:
            query = query.where(Order.status == status)

        query = query.offset(skip).limit(limit).order_by(Order.created_at.desc())

        result = await self._db.execute(query)
        orders = result.scalars().all()

        # For each order, get items
        responses = []
        for order in orders:
            result = await self._db.execute(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
            order_items = result.scalars().all()

            responses.append(
                OrderResponse(
                    id=str(order.id),
                    order_number=order.order_number,
                    buyer_id=str(order.buyer_id),
                    status=order.status,
                    currency=order.currency,
                    total_amount=order.total_amount,
                    idempotency_key=order.idempotency_key,
                    created_at=order.created_at,
                    updated_at=order.updated_at,
                    items=[
                        {
                            "id": str(item.id),
                            "product_id": str(item.product_id),
                            "variant_id": str(item.variant_id) if item.variant_id else None,
                            "merchant_id": str(item.merchant_id),
                            "quantity": item.quantity,
                            "unit_price": item.unit_price,
                            "currency": item.currency,
                            "line_total": item.line_total,
                        }
                        for item in order_items
                    ],
                )
            )

        return responses
