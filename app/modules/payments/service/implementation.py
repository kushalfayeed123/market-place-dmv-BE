# app/modules/payments/service/implementation.py
"""
Concrete implementation of the payment service.
Handles database operations for payments using SQLAlchemy.
"""

import uuid

from app.core.security import to_uuid
from app.models.ledger_entry import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.payment_transaction import PaymentTransaction
from app.models.webhook_event import WebhookEvent
from app.modules.payments.providers.registry import (
    is_provider_implemented,
    get_provider,
)
from app.modules.payments.service.base import PaymentService
from app.schemas.payments import (
    PaymentProcess,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
    WebhookResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentServiceImpl(PaymentService):
    """
    Database-backed implementation of PaymentService.
    
    This class encapsulates all database operations for payments,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def process_payment(
        self, payment_data: PaymentProcess, user_id: str
    ) -> PaymentResponse:
        """
        Process a payment for an order in the database.
        
        Args:
            payment_data: The payment processing data.
            user_id: The user ID initiating the payment.
            
        Returns:
            The payment response.
            
        Raises:
            ValueError: If order not found or not authorized.
        """
        # Verify order exists
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(payment_data.order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise ValueError("Order not found")

        # Verify user has permission to pay for this order
        if order.buyer_id != to_uuid(user_id):
            raise ValueError("Not authorized to pay for this order")

        provider_key = payment_data.provider

        # ── Pay on Delivery (merchant-confirmed) ──────────────────────────
        # No online provider is involved.  The order is placed into
        # awaiting_approval so the merchant can confirm payment once the
        # goods are delivered.  A payout-hold ledger entry is created per
        # merchant line item and released when the merchant approves.
        if provider_key == "pay_on_delivery":
            if order.status in (
                OrderStatus.PAID.value,
                OrderStatus.AWAITING_APPROVAL.value,
            ):
                raise ValueError(
                    f"Order cannot use Pay on Delivery in status '{order.status}'"
                )

            payment_transaction = PaymentTransaction(
                order_id=order.id,
                provider="pay_on_delivery",
                provider_reference=f"pod_{order.order_number}",
                status="pending_verification",
                amount=order.total_amount,
                currency=order.currency,
                payment_url=None,
            )
            self._db.add(payment_transaction)

            # Payout-hold entries per merchant line item (released on approval).
            await _create_payout_hold_entries(
                self._db, order, payment_transaction, user_id
            )

            order.status = OrderStatus.AWAITING_APPROVAL.value
            await self._db.commit()
            await self._db.refresh(payment_transaction)

            return PaymentResponse(
                id=str(payment_transaction.id),
                order_id=str(payment_transaction.order_id),
                provider=payment_transaction.provider,
                provider_reference=payment_transaction.provider_reference,
                status=payment_transaction.status,
                amount=payment_transaction.amount,
                currency=payment_transaction.currency,
                created_at=payment_transaction.created_at,
                payment_url=None,
                payment_method="pay_on_delivery",
            )

        # Verify the payment provider is implemented and available
        if not is_provider_implemented(provider_key):
            raise ValueError(
                f"Payment provider '{provider_key}' is not yet implemented. "
                f"Available providers: paystack"
            )
        provider = get_provider(provider_key)
        if provider is None:
            raise ValueError(f"Unknown payment provider '{provider_key}'")

        # Initialise the payment with the provider.
        # When Paystack credentials are not configured (dev/test), the provider
        # falls back to a local stub that returns a reference + mock URL.
        init_result = await provider.initialize_transaction(
            order_id=str(order.id),
            amount=order.total_amount,
            currency=order.currency,
            buyer_email=None,
            metadata={"order_number": order.order_number},
        )

        # Create payment transaction with the provider's reference
        # The webhook (not this endpoint) will update it to "success"
        payment_transaction = PaymentTransaction(
            order_id=order.id,
            provider=payment_data.provider,
            provider_reference=init_result.provider_reference,
            status=init_result.status,
            amount=order.total_amount,
            currency=order.currency,
            payment_url=init_result.payment_url,
        )

        self._db.add(payment_transaction)

        # Order status remains "pending" until webhook confirms payment
        await self._db.commit()
        await self._db.refresh(payment_transaction)

        return PaymentResponse(
            id=str(payment_transaction.id),
            order_id=str(payment_transaction.order_id),
            provider=payment_transaction.provider,
            provider_reference=payment_transaction.provider_reference,
            status=payment_transaction.status,
            amount=payment_transaction.amount,
            currency=payment_transaction.currency,
            created_at=payment_transaction.created_at,
            payment_url=init_result.payment_url,
            payment_method=None,
        )

    async def get_payment(self, payment_id: str) -> PaymentResponse | None:
        """
        Get a payment by ID from the database.
        
        Args:
            payment_id: The payment ID.
            
        Returns:
            The payment response if found, None otherwise.
        """
        result = await self._db.execute(
            select(PaymentTransaction).where(PaymentTransaction.id == to_uuid(payment_id))
        )
        payment = result.scalar_one_or_none()

        if payment is None:
            return None

        return PaymentResponse(
            id=str(payment.id),
            order_id=str(payment.order_id),
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
            created_at=payment.created_at,
            payment_url=payment.payment_url,
            payment_method="pay_on_delivery" if payment.provider == "pay_on_delivery" else None,
        )

    async def get_payment_by_order(self, order_id: str, user_id: str) -> PaymentResponse | None:
        """
        Get the most recent payment for an order, verifying the buyer owns it.

        Args:
            order_id: The order ID.
            user_id: The buyer's user ID for access control.

        Returns:
            The payment response if found, None otherwise.

        Raises:
            ValueError: If the order exists but the user is not the buyer.
        """
        # Verify the order exists and the user owns it
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise ValueError("Order not found")

        if order.buyer_id != to_uuid(user_id):
            raise ValueError("Not authorized to view payments for this order")

        # Get the most recent payment for this order
        result = await self._db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.order_id == to_uuid(order_id))
            .order_by(PaymentTransaction.created_at.desc())
            .limit(1)
        )
        payment = result.scalar_one_or_none()

        if payment is None:
            return None

        return PaymentResponse(
            id=str(payment.id),
            order_id=str(payment.order_id),
            provider=payment.provider,
            provider_reference=payment.provider_reference,
            status=payment.status,
            amount=payment.amount,
            currency=payment.currency,
            created_at=payment.created_at,
            payment_url=payment.payment_url,
            payment_method="pay_on_delivery" if payment.provider == "pay_on_delivery" else None,
        )

    async def list_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        order_id: str | None = None,
        status: str | None = None,
        merchant_id: str | None = None,
    ) -> list[PaymentResponse]:
        """
        List payments with optional filtering from the database.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            order_id: Filter by order ID.
            status: Filter by payment status.
            merchant_id: Filter by merchant (joins through Order → OrderItem).

        Returns:
            List of payment responses.
        """
        from app.models.order import Order
        from app.models.order_item import OrderItem

        query = select(PaymentTransaction)

        if order_id:
            query = query.where(PaymentTransaction.order_id == order_id)
        if status:
            query = query.where(PaymentTransaction.status == status)
        if merchant_id:
            query = (
                query.join(Order, PaymentTransaction.order_id == Order.id)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .where(OrderItem.merchant_id == to_uuid(merchant_id))
            )

        query = query.offset(skip).limit(limit)
        result = await self._db.execute(query)
        payments = result.scalars().all()

        return [
            PaymentResponse(
                id=str(payment.id),
                order_id=str(payment.order_id),
                provider=payment.provider,
                provider_reference=payment.provider_reference,
                status=payment.status,
                amount=payment.amount,
                currency=payment.currency,
                created_at=payment.created_at,
                payment_url=payment.payment_url,
                payment_method="pay_on_delivery" if payment.provider == "pay_on_delivery" else None,
            )
            for payment in payments
        ]

    async def process_refund(
        self, payment_id: str, refund_data: RefundRequest
    ) -> RefundResponse:
        """
        Process a refund for a payment in the database.
        
        Args:
            payment_id: The payment ID to refund.
            refund_data: The refund request data.
            
        Returns:
            The refund response.
            
        Raises:
            ValueError: If payment not found or already refunded.
        """
        # Get the original payment
        result = await self._db.execute(
            select(PaymentTransaction).where(PaymentTransaction.id == payment_id)
        )
        payment_transaction = result.scalar_one_or_none()

        if not payment_transaction:
            raise ValueError("Payment not found")

        if payment_transaction.status == "refunded":
            raise ValueError("Payment already refunded")

        # Calculate refund amount
        refund_amount = refund_data.amount or payment_transaction.amount

        # Create refund transaction
        refund_transaction = PaymentTransaction(
            order_id=payment_transaction.order_id,
            provider=payment_transaction.provider,
            provider_reference=f"{payment_transaction.provider}_refund_{uuid.uuid4()}",
            status="refunded",
            amount=refund_amount,
            currency=payment_transaction.currency,
        )

        self._db.add(refund_transaction)

        # Update original payment status
        payment_transaction.status = "refunded"
        await self._db.commit()
        await self._db.refresh(refund_transaction)

        return RefundResponse(
            id=str(refund_transaction.id),
            order_id=str(refund_transaction.order_id),
            provider=refund_transaction.provider,
            provider_reference=refund_transaction.provider_reference,
            status=refund_transaction.status,
            amount=refund_transaction.amount,
            currency=refund_transaction.currency,
            created_at=refund_transaction.created_at,
            original_payment_id=str(payment_transaction.id),
        )

    async def handle_webhook(
        self, provider: str, event_type: str, event_id: str, payload: bytes
    ) -> WebhookResponse:
        """
        Handle an incoming webhook from a payment provider.
        
        Args:
            provider: The payment provider name.
            event_type: The webhook event type.
            event_id: The webhook event ID.
            payload: The raw webhook payload.
            
        Returns:
            The webhook response.
        """
        # Check if we've already processed this webhook (idempotency)
        result = await self._db.execute(
            select(WebhookEvent).where(
                WebhookEvent.provider == provider,
                WebhookEvent.event_id == event_id,
            )
        )
        existing_event = result.scalar_one_or_none()

        if existing_event:
            return WebhookResponse(
                status="success",
                message="Webhook already processed",
                event_id=event_id,
            )

                # Store webhook event
        webhook_event = WebhookEvent(
            provider=provider,
            event_id=event_id,
            event_type=event_type,
            payload=str(payload),
        )

        self._db.add(webhook_event)

        # If this is a payment success webhook, update the payment status
        # and the order status so the buyer's PaymentCapturePanel refreshes.
        success_events = {"charge.success", "payment.success", "payment.succeeded"}
        if event_type in success_events:
            import json as _json
            try:
                payload_dict = _json.loads(payload) if isinstance(payload, (str, bytes)) else payload
                ref = None
                if isinstance(payload_dict, dict):
                    ref = payload_dict.get("reference") or (
                        payload_dict.get("data", {}) or {}
                    ).get("reference")
                if ref:
                    existing = await self._db.execute(
                        select(PaymentTransaction).where(
                            PaymentTransaction.provider == provider,
                            PaymentTransaction.provider_reference == ref,
                        )
                    )
                    pt = existing.scalar_one_or_none()
                    if pt and pt.status != "success":
                        pt.status = "success"
                        # Mark the order as paid
                        o = await self._db.get(Order, pt.order_id)
                        if o and o.status == "pending":
                            o.status = "paid"
                        await self._db.refresh(pt)
            except (ValueError, TypeError):
                pass
        await self._db.commit()

        return WebhookResponse(
            status="success",
            message="Webhook received and stored",
            event_id=event_id,
        )


async def _create_payout_hold_entries(db, order, payment_transaction, created_by: str) -> None:
    """Create payout-hold ledger entries per merchant line item.

    Mirrors the ledger entries in ``submit_proof_of_payment`` so that
    ``approve_order``'s payout-release balances against them.  Funds stay
    held until the merchant confirms pay-on-delivery payment.
    """
    group_id = uuid.uuid4()
    items_result = db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )
    order_items = items_result.scalars().all()

    for item in order_items:
        # Sale entry (debit — platform records the sale)
        db.add(
            LedgerEntry(
                entry_group_id=group_id,
                account_type="platform_revenue",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.DEBIT.value,
                entry_type=LedgerEntryType.SALE.value,
                amount=abs(item.line_total),
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(created_by),
            )
        )
        # Payout hold entry (credit — funds held for merchant until approval)
        db.add(
            LedgerEntry(
                entry_group_id=group_id,
                account_type="merchant_wallet",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.CREDIT.value,
                entry_type=LedgerEntryType.PAYOUT_HOLD.value,
                amount=abs(item.line_total),
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(created_by),
            )
        )
