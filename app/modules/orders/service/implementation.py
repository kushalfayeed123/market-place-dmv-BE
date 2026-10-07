# app/modules/orders/service/implementation.py
"""
Concrete implementation of the order service.
Handles database operations for orders using SQLAlchemy.
"""


import uuid
from datetime import datetime, timezone

from app.core.security import to_uuid
from app.models.inventory import Inventory
from app.models.ledger_entry import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.merchant import Merchant
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.product_variant import ProductVariant
from app.modules.orders.service.base import OrderService
from app.schemas.orders import (
    CheckoutRequest,
    CheckoutResponse,
    OrderApprovalResponse,
    OrderResponse,
    ProofOfPaymentRequest,
    ProofOfPaymentResponse,
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
            item_count=sum(item_data["quantity"] for item_data in order_items_data),
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

        # Fetch merchant name from the first item's merchant
        merchant_name = None
        merchant_id_str = None
        if order_items:
            first_merchant_id = order_items[0].merchant_id
            merchant_id_str = str(first_merchant_id)
            m_result = await self._db.execute(
                select(Merchant).where(Merchant.id == first_merchant_id)
            )
            merchant = m_result.scalar_one_or_none()
            if merchant:
                merchant_name = merchant.business_name

        return OrderResponse(
            id=str(order.id),
            order_number=order.order_number,
            buyer_id=str(order.buyer_id),
            status=order.status,
            currency=order.currency,
            total_amount=order.total_amount,
            idempotency_key=order.idempotency_key,
            item_count=sum(item.quantity for item in order_items),
            merchant_id=merchant_id_str,
            merchant_name=merchant_name,
            payment_status="paid" if order.status == OrderStatus.PAID.value else None,
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
                    item_count=sum(item.quantity for item in order_items),
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

    async def submit_proof_of_payment(
        self,
        order_id: str,
        buyer_id: str,
        proof_data: ProofOfPaymentRequest,
    ) -> ProofOfPaymentResponse:
        """Record proof of payment for an order (offline / bank transfer).

        Creates a PaymentTransaction with status 'pending_verification',
        a sale ledger entry (debit platform_rev) and a payout_hold entry
        (credit to the merchant wallet), then transitions the order to
        'awaiting_approval'.
        """
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(order_id))
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("Order not found")
        if str(order.buyer_id) != str(buyer_id):
            raise ValueError("Not authorized to submit proof for this order")
        if order.status not in (OrderStatus.PENDING.value, OrderStatus.AWAITING_APPROVAL.value):
            raise ValueError(
                f"Order cannot accept proof in status '{order.status}'"
            )

        # Create payment transaction with pending_verification
        payment_transaction = PaymentTransaction(
            order_id=order.id,
            provider=proof_data.provider,
            provider_reference=proof_data.reference,
            status="pending_verification",
            amount=order.total_amount,
            currency=order.currency,
            raw_payload={"proof_image_url": proof_data.proof_image_url},
        )
        self._db.add(payment_transaction)

        # Create ledger entries: sale (debit) + payout_hold (credit) per merchant
        group_id = uuid.uuid4()
        items_result = await self._db.execute(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
        order_items = items_result.scalars().all()

        for item in order_items:
            # Sale entry (debit -- platform records the sale)
            self._db.add(LedgerEntry(
                entry_group_id=group_id,
                account_type="platform_revenue",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.DEBIT.value,
                entry_type=LedgerEntryType.SALE.value,
                amount=abs(item.line_total),
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(buyer_id),
            ))
            # Payout hold entry (credit -- funds held for merchant until approval)
            self._db.add(LedgerEntry(
                entry_group_id=group_id,
                account_type="merchant_wallet",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.CREDIT.value,
                entry_type=LedgerEntryType.PAYOUT_HOLD.value,
                amount=abs(item.line_total),
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(buyer_id),
            ))

        # Update order status to awaiting_approval
        order.status = OrderStatus.AWAITING_APPROVAL.value
        await self._db.commit()
        await self._db.refresh(payment_transaction)
        await self._db.refresh(order)

        return ProofOfPaymentResponse(
            order_id=str(order.id),
            order_number=order.order_number,
            status=order.status,
            payment_id=str(payment_transaction.id),
            payment_status=payment_transaction.status,
            message="Proof of payment submitted. Awaiting merchant approval.",
            created_at=payment_transaction.created_at,
        )

    async def approve_order(
        self,
        order_id: str,
        merchant_id: str,
    ) -> OrderApprovalResponse:
        """Merchant approves an order with proof of payment on file."""
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(order_id))
        )
        order = result.scalar_one_or_none()
        if order is None:
            raise ValueError("Order not found")

        # Verify this merchant owns at least one item in the order
        items_result = await self._db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.merchant_id == to_uuid(merchant_id),
            )
        )
        merchant_items = items_result.scalars().all()
        if not merchant_items:
            raise ValueError("Not authorized to approve this order")

        if order.status != OrderStatus.AWAITING_APPROVAL.value:
            raise ValueError(
                f"Order cannot be approved in status '{order.status}'"
            )

        # Create ledger entry: payout_release (credit -- moves held funds to available)
        group_id = uuid.uuid4()
        total_release = sum(abs(i.line_total) for i in merchant_items)
        self._db.add(LedgerEntry(
            entry_group_id=group_id,
            account_type="merchant_wallet",
            merchant_id=to_uuid(merchant_id),
            direction=LedgerDirection.CREDIT.value,
            entry_type=LedgerEntryType.PAYOUT_RELEASE.value,
            amount=total_release,
            currency=merchant_items[0].currency,
            order_id=order.id,
            created_by=str(merchant_id),
        ))

        # Update order status to paid
        order.status = OrderStatus.PAID.value
        await self._db.commit()
        await self._db.refresh(order)

        return OrderApprovalResponse(
            order_id=str(order.id),
            order_number=order.order_number,
            status=order.status,
            payment_status="paid",
            ledger_entries_created=1,
            message=f"Order approved. {len(merchant_items)} item(s) marked for payout.",
            updated_at=order.updated_at,
        )
