# app/modules/payments/service/implementation.py
"""
Concrete implementation of the payment service.
Handles database operations for payments using SQLAlchemy.
"""

import json
import uuid

from app.core.security import to_uuid
from app.models.commission_plan import CommissionPlan
from app.models.ledger_entry import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.merchant import Merchant
from app.models.merchant_payout_account import MerchantPayoutAccount
from app.models.notification import NotificationChannel, NotificationType
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.modules.payments.providers.base import SplitLeg
from app.modules.notifications.service.base import NotificationService
from app.modules.orders.lookup import get_order_by_ref
from app.modules.payments.providers.registry import (
    is_provider_implemented,
    get_provider,
)
from app.modules.payments.service.base import PaymentService
from app.schemas.notification import NotificationCreate
from app.schemas.payments import (
    PaymentProcess,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
    WebhookResponse,
)
from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession


class PaymentServiceImpl(PaymentService):
    """
    Database-backed implementation of PaymentService.

    This class encapsulates all database operations for payments,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession, notification_service: NotificationService | None = None):
        """
        Initialize the service with a database session.

        Args:
            db: The async SQLAlchemy session to use for queries.
            notification_service: Optional notification service.
        """
        self._db = db
        self._notification_service = notification_service

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
        # Verify order exists — accepts a UUID or an order number (ORD-…)
        order = await get_order_by_ref(self._db, payment_data.order_id)

        if not order:
            raise ValueError("Order not found")

        # Verify user has permission to pay for this order
        if order.buyer_id != to_uuid(user_id):
            raise ValueError("Not authorized to pay for this order")

        provider_key = payment_data.provider

        if provider_key != "pay_on_delivery":
            existing_result = await self._db.execute(
                select(PaymentTransaction)
                .where(
                    PaymentTransaction.order_id == order.id,
                    PaymentTransaction.status.in_(("success", "initialized")),
                )
                .order_by(
                    case(
                        (PaymentTransaction.status == "success", 0),
                        else_=1,
                    ),
                    PaymentTransaction.created_at.desc(),
                )
                .limit(1)
            )
            existing_payment = existing_result.scalar_one_or_none()
            existing_split_code = None
            existing_subaccount = None
            if (
                existing_payment is not None
                and existing_payment.provider == provider_key
                and existing_payment.raw_payload
            ):
                try:
                    existing_payload = json.loads(existing_payment.raw_payload)
                except (json.JSONDecodeError, TypeError):
                    existing_payload = {}
                if isinstance(existing_payload, dict):
                    existing_split_code = existing_payload.get("split_code")
                    existing_subaccount = existing_payload.get("subaccount")

            if existing_payment is not None and (
                existing_payment.status == "success"
                or existing_split_code
                or existing_subaccount
            ):
                return PaymentResponse(
                    id=str(existing_payment.id),
                    order_id=str(existing_payment.order_id),
                    provider=existing_payment.provider,
                    provider_reference=existing_payment.provider_reference,
                    status=existing_payment.status,
                    amount=existing_payment.amount,
                    currency=existing_payment.currency,
                    created_at=existing_payment.created_at,
                    payment_url=existing_payment.payment_url,
                    payment_method=None,
                )

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

            # Pay on Delivery only makes sense for physical goods — a digital
            # download or service cannot be "paid for on delivery".
            kind_result = await self._db.execute(
                select(Product.fulfillment_type)
                .join(OrderItem, OrderItem.product_id == Product.id)
                .where(OrderItem.order_id == order.id)
            )
            kinds = {row[0] for row in kind_result.all()}
            if "physical" not in kinds:
                raise ValueError(
                    "Pay on Delivery is only available for orders with physical products."
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

        # ── Merchant settlement routing ───────────────────────────────────
        # Paystack dynamic flat splits reject subaccount shares below NGN 100.
        # A direct subaccount transaction supports smaller single-merchant
        # orders, while multi-merchant orders continue to use a transaction split.
        split_code, subaccount, transaction_charge = await _create_order_split(
            self._db, order, provider
        )

        # Resolve the buyer's real email — Paystack requires a customer email
        # on transaction initialize; it must never be a placeholder.
        buyer = (
            await self._db.execute(select(User).where(User.id == order.buyer_id))
        ).scalar_one_or_none()
        if buyer is None or not buyer.email:
            raise ValueError("Buyer account has no email address — cannot initialize payment")
        buyer_email = buyer.email

        # Initialise the payment with the provider.
        # When Paystack credentials are not configured (dev/test), the provider
        # falls back to a local stub that returns a reference + mock URL.
        init_result = await provider.initialize_transaction(
            order_id=str(order.id),
            amount=order.total_amount,
            currency=order.currency,
            buyer_email=buyer_email,
            metadata={"order_number": order.order_number},
            split_code=split_code,
            subaccount=subaccount,
            transaction_charge=transaction_charge,
        )

        # Create payment transaction with the provider's reference
        # The webhook (not this endpoint) will update it to "success"
        settlement_payload = {}
        if split_code:
            settlement_payload["split_code"] = split_code
        if subaccount:
            settlement_payload["subaccount"] = subaccount
        if transaction_charge is not None:
            settlement_payload["transaction_charge"] = transaction_charge
        raw_payload = json.dumps(settlement_payload) if settlement_payload else None
        payment_transaction = PaymentTransaction(
            order_id=order.id,
            provider=payment_data.provider,
            provider_reference=init_result.provider_reference,
            status=init_result.status,
            amount=order.total_amount,
            currency=order.currency,
            payment_url=init_result.payment_url,
            raw_payload=raw_payload,
        )

        # Record the customer email on the transaction for traceability.
        if raw_payload:
            payload_obj = json.loads(raw_payload)
        else:
            payload_obj = {}
        payload_obj["customer_email"] = buyer_email
        payload_obj["order_number"] = order.order_number
        payment_transaction.raw_payload = json.dumps(payload_obj)

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
        # Verify the order exists and the user owns it (UUID or order number)
        order = await get_order_by_ref(self._db, order_id)

        if not order:
            raise ValueError("Order not found")

        if order.buyer_id != to_uuid(user_id):
            raise ValueError("Not authorized to view payments for this order")

        # Get the most recent payment for this order
        result = await self._db.execute(
            select(PaymentTransaction)
            .where(PaymentTransaction.order_id == order.id)
            .order_by(
                case(
                    (PaymentTransaction.status == "refunded", 0),
                    (PaymentTransaction.status == "success", 1),
                    else_=2,
                ),
                PaymentTransaction.created_at.desc(),
            )
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

    async def verify_payment_by_order(
        self, order_id: str, user_id: str
    ) -> PaymentResponse | None:
        """Verify and persist a pending provider payment for its buyer.

        ``order_id`` may be the order's UUID or its order number.
        """
        order = await get_order_by_ref(self._db, order_id)
        if order is None:
            raise ValueError("Order not found")
        if order.buyer_id != to_uuid(user_id):
            raise ValueError("Not authorized to verify this order's payment")

        payment_result = await self._db.execute(
            select(PaymentTransaction)
            .where(
                PaymentTransaction.order_id == order.id,
                PaymentTransaction.status == "initialized",
                PaymentTransaction.provider == "paystack",
            )
            .order_by(PaymentTransaction.created_at.desc())
            .limit(1)
        )
        payment = payment_result.scalar_one_or_none()
        if payment is None:
            return await self.get_payment_by_order(order_id, user_id)

        provider = get_provider(payment.provider)
        if provider is None:
            raise ValueError(f"Payment provider '{payment.provider}' is unavailable")
        verification = await provider.verify_transaction_details(
            payment.provider_reference
        )
        if verification is None:
            return await self.get_payment_by_order(order_id, user_id)

        if verification.status == "success":
            if verification.currency.upper() != payment.currency.upper():
                raise ValueError(
                    "Provider payment currency does not match the order."
                )
            # The provider adds its commission at the point of payment, so the
            # actual amount charged (verification.amount) may exceed the order
            # total — record the actual paid amount reported by the provider.
            await self._confirm_payment_success(
                payment, order, paid_amount=verification.amount
            )
        elif verification.status == "failed":
            payment.status = "failed"

        if payment.status in ("success", "failed"):
            await self._db.commit()
            await self._db.refresh(payment)

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
            payment_method=None,
        )

    async def _confirm_payment_success(
        self,
        pt: PaymentTransaction,
        order: Order | None,
        paid_amount: int | None = None,
    ) -> None:
        """Mark a payment transaction successful and release value (ledger + notifications).

        Idempotent — no-op when the payment is already successful.
        ``paid_amount`` is the actual amount the provider charged (order total +
        provider commission), taken from the provider's verification endpoint.
        """
        if pt.status == "success":
            return
        pt.status = "success"
        if paid_amount is not None and paid_amount >= 0 and paid_amount != pt.amount:
            pt.amount = paid_amount
        if order is not None and order.status == OrderStatus.PENDING.value:
            order.status = OrderStatus.PAID.value

        if order is None:
            return

        # ── Ledger: per-item sale + commission + payout_hold (idempotent) ──
        already = await self._db.execute(
            select(LedgerEntry.id)
            .where(LedgerEntry.payment_transaction_id == pt.id)
            .limit(1)
        )
        if already.scalar_one_or_none() is None:
            await post_order_ledger_entries(
                self._db, order, pt, created_by=str(order.buyer_id)
            )

        # ── Notifications: payment confirmed ──────────────────────────
        if self._notification_service:
            try:
                items_result = await self._db.execute(
                    select(OrderItem).where(OrderItem.order_id == order.id)
                )
                order_items = items_result.scalars().all()
                merchant_ids = {str(i.merchant_id) for i in order_items}

                await self._notification_service.create_notification(
                    NotificationCreate(
                        user_id=str(order.buyer_id),
                        type=NotificationType.PAYMENT_CONFIRMED.value,
                        channel=NotificationChannel.EMAIL.value,
                        subject=f"Payment confirmed — Order {order.order_number}",
                        body=(
                            f"Your payment for order {order.order_number} has been confirmed. "
                            f"Your order is now being prepared for fulfillment."
                        ),
                        related_order_id=str(order.id),
                        related_payment_id=str(pt.id),
                        payload={"order_number": order.order_number, "action_label": "View order"},
                    )
                )
                for m_id in merchant_ids:
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            merchant_id=m_id,
                            type=NotificationType.MERCHANT_NEW_ORDER.value,
                            channel=NotificationChannel.PUSH.value,
                            subject=f"New order paid — {order.order_number}",
                            body=(
                                f"Order {order.order_number} has been paid "
                                f"({order.total_amount} {order.currency}). Please fulfill."
                            ),
                            related_order_id=str(order.id),
                            related_payment_id=str(pt.id),
                        )
                    )
            except (ValueError, TypeError):
                pass

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

        # ── Ledger: refund entries per merchant line item ──────────────────
        # Each item's sale is reversed: refund debit against the merchant wallet
        # (reduces their balance) and credit back to platform_revenue, grouped
        # in one entry_group and linked to the original payment transaction.
        # Partial refunds (one item in a multi-merchant order) map to that
        # item's split leg. The design doc: "ledger records a refund entry
        # against the specific merchant subaccount".
        order = await self._db.get(Order, payment_transaction.order_id)
        if order is not None:
            group_id = uuid.uuid4()
            items_res = await self._db.execute(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
            order_items = items_res.scalars().all()
            # Pro-rate the refund across items when the refund is partial.
            total = sum(abs(i.line_total) for i in order_items) or 1
            for item in order_items:
                item_refund = (
                    refund_amount
                    if refund_amount == payment_transaction.amount
                    else (abs(item.line_total) * refund_amount) // total
                )
                if item_refund <= 0:
                    continue
                # Refund debit against merchant wallet (reduces merchant balance)
                self._db.add(
                    LedgerEntry(
                        entry_group_id=group_id,
                        account_type="merchant_wallet",
                        merchant_id=item.merchant_id,
                        direction=LedgerDirection.DEBIT.value,
                        entry_type=LedgerEntryType.REFUND.value,
                        amount=item_refund,
                        currency=item.currency,
                        order_id=order.id,
                        payment_transaction_id=payment_transaction.id,
                        created_by="system",
                    )
                )
                # Refund credit back to platform revenue
                self._db.add(
                    LedgerEntry(
                        entry_group_id=group_id,
                        account_type="platform_revenue",
                        merchant_id=item.merchant_id,
                        direction=LedgerDirection.CREDIT.value,
                        entry_type=LedgerEntryType.REFUND.value,
                        amount=item_refund,
                        currency=item.currency,
                        order_id=order.id,
                        payment_transaction_id=payment_transaction.id,
                        created_by="system",
                    )
                )
            # Also reverse the merchant's payout_hold so held funds drop.
            holds_res = await self._db.execute(
                select(LedgerEntry).where(
                    LedgerEntry.order_id == order.id,
                    LedgerEntry.entry_type == LedgerEntryType.PAYOUT_HOLD.value,
                    LedgerEntry.id.not_in(
                        select(LedgerEntry.supersedes_entry_id).where(
                            LedgerEntry.supersedes_entry_id.isnot(None)
                        )
                    ),
                )
            )
            for hold in holds_res.scalars().all():
                self._db.add(
                    LedgerEntry(
                        entry_group_id=group_id,
                        account_type="merchant_wallet",
                        merchant_id=hold.merchant_id,
                        direction=LedgerDirection.DEBIT.value,
                        entry_type=LedgerEntryType.PAYOUT_HOLD.value,
                        amount=hold.amount,
                        currency=hold.currency,
                        order_id=order.id,
                        supersedes_entry_id=hold.id,
                        created_by="system",
                    )
                )

        # Ask the provider to refund the transaction (best-effort; the webhook
        # will confirm). Partial refunds pass the amount through.
        provider = get_provider(payment_transaction.provider)
        if provider is not None and hasattr(provider, "initiate_refund"):
            try:
                await provider.initiate_refund(
                    payment_transaction.provider_reference,
                    amount=refund_amount if refund_amount != payment_transaction.amount else None,
                )
            except Exception:
                pass  # ledger already records the refund; provider sync is best-effort

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
                        o = await self._db.get(Order, pt.order_id)
                        # The webhook alone is NOT trusted: confirm with the
                        # provider's verification endpoint before releasing
                        # value (ledger entries, order → paid, notifications).
                        # When the provider is not configured (dev/stub mode),
                        # verification is None and the webhook is accepted as-is.
                        provider_obj = get_provider(provider)
                        verification = None
                        verify_unreachable = False
                        if provider_obj is not None:
                            try:
                                verification = await provider_obj.verify_transaction_details(ref)
                            except RuntimeError:
                                verify_unreachable = True
                        if verification is not None and verification.status in ("failed", "reversed"):
                            # Provider explicitly disputes the webhook — do not
                            # confirm or release value.
                            pass
                        elif verification is not None or not verify_unreachable:
                            # The webhook is the source of truth; when the provider
                            # confirms success, record the actual amount paid
                            # (order total + provider commission) from the provider.
                            paid_amount = (
                                verification.amount
                                if verification is not None and verification.status == "success"
                                else None
                            )
                            await self._confirm_payment_success(
                                pt, o, paid_amount=paid_amount
                            )
                        # verify_unreachable: leave the payment initialized; the
                        # buyer-facing /verify endpoint reconciles later.
            except (ValueError, TypeError):
                pass

        # Payment failure → notify buyer
        failure_events = {"charge.failed", "payment.failed", "payment.failure"}
        if event_type in failure_events:
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
                    if pt and pt.status != "failed":
                        pt.status = "failed"
                        o = await self._db.get(Order, pt.order_id)
                        if self._notification_service and o:
                            try:
                                await self._notification_service.create_notification(
                                    NotificationCreate(
                                        user_id=str(o.buyer_id),
                                        type=NotificationType.PAYMENT_FAILED.value,
                                        channel=NotificationChannel.EMAIL.value,
                                        subject=f"Payment failed — Order {o.order_number}",
                                        body=(
                                            f"Your payment for order {o.order_number} could not be completed. "
                                            f"Please try again or contact support."
                                        ),
                                        related_order_id=str(o.id),
                                        related_payment_id=str(pt.id),
                                        payload={"order_number": o.order_number, "action_label": "View order"},
                                    )
                                )
                            except Exception:
                                pass
            except (ValueError, TypeError):
                pass

        await self._db.commit()

        return WebhookResponse(
            status="success",
            message="Webhook received and stored",
            event_id=event_id,
        )


def compute_commission(line_total: int, plan: CommissionPlan | None) -> int:
    """Commission owed to the platform for one line, in minor units.

    ``percentage_bps`` is basis points (1000 = 10%) plus an optional flat fee.
    """
    if plan is None or line_total <= 0:
        return 0
    pct = (line_total * plan.percentage_bps) // 10_000
    return pct + (plan.flat_fee_minor or 0)


async def _merchant_legs_for_order(db, order, provider_key: str) -> list[tuple]:
    """Group an order's items by merchant.

    Returns a list of ``(merchant, subaccount_code, gross_total, plan)`` tuples.
    """
    from app.models.order_item import OrderItem

    items = (
        (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
        .scalars()
        .all()
    )
    by_merchant: dict = {}
    for item in items:
        by_merchant.setdefault(item.merchant_id, []).append(item)

    legs = []
    for merchant_id, merchant_items in by_merchant.items():
        merchant = (
            await db.execute(select(Merchant).where(Merchant.id == merchant_id))
        ).scalar_one_or_none()
        if merchant is None:
            continue
        plan = (
            await db.execute(
                select(CommissionPlan).where(CommissionPlan.id == merchant.commission_plan_id)
            )
        ).scalar_one_or_none()
        accounts = (
            await db.execute(
                select(MerchantPayoutAccount).where(
                    MerchantPayoutAccount.merchant_id == merchant_id,
                    MerchantPayoutAccount.provider == provider_key,
                    MerchantPayoutAccount.currency == order.currency,
                    MerchantPayoutAccount.is_active.is_(True),
                )
            )
        ).scalars().all()
        if not accounts:
            raise ValueError(
                f"Merchant '{merchant.business_name}' must configure an active "
                f"{provider_key} payout account in {order.currency} before this "
                "order can be paid online."
            )
        if len(accounts) > 1:
            raise ValueError(
                f"Merchant '{merchant.business_name}' has multiple active "
                f"{provider_key} payout accounts in {order.currency}."
            )
        subaccount_code = (accounts[0].external_ref or "").strip()
        if not subaccount_code:
            raise ValueError(
                f"Merchant '{merchant.business_name}' has no {provider_key} subaccount "
                f"code configured for {order.currency}."
            )
        gross = sum(abs(i.line_total) for i in merchant_items)
        legs.append((merchant, subaccount_code, gross, plan))
    return legs


async def _create_order_split(
    db, order, provider
) -> tuple[str | None, str | None, int | None]:
    """Build merchant settlement instructions for an order.

    Single-merchant orders use the provider's direct subaccount settlement
    fields; multi-merchant orders use a transaction split. Merchant payouts
    are ``gross - commission`` and the platform retains the commission.
    """
    provider_key = getattr(provider, "provider_key", "")
    if not provider_key or not hasattr(provider, "create_split"):
        raise ValueError("Selected payment provider does not support merchant settlement splits")

    legs_data = await _merchant_legs_for_order(db, order, provider_key)
    if not legs_data:
        raise ValueError("Cannot create payment split for an order without merchant items")

    if len(legs_data) == 1:
        _, subaccount_code, gross, plan = legs_data[0]
        commission = compute_commission(gross, plan)
        if commission < 0 or commission >= gross:
            merchant = legs_data[0][0]
            raise ValueError(
                f"Invalid commission for merchant '{merchant.business_name}': "
                "the merchant settlement share must be greater than zero."
            )
        return None, subaccount_code, commission

    split_legs: list[SplitLeg] = []
    total_commission = 0
    for merchant, subaccount_code, gross, plan in legs_data:
        commission = compute_commission(gross, plan)
        if commission < 0 or commission >= gross:
            raise ValueError(
                f"Invalid commission for merchant '{merchant.business_name}': "
                "the merchant settlement share must be greater than zero."
            )
        total_commission += commission
        net = gross - commission
        split_legs.append(
            SplitLeg(
                subaccount=subaccount_code,
                amount=net,
                currency=order.currency,
                label=merchant.business_name,
            )
        )
    if total_commission > 0:
        # Paystack retains the unassigned remainder in the platform account.
        split_legs.append(
            SplitLeg(
                subaccount=None,
                amount=total_commission,
                currency=order.currency,
                label="platform_commission",
            )
        )
    result = await provider.create_split(
        name=f"order_{order.order_number}", legs=split_legs, currency=order.currency
    )
    if result is None or not result.split_code:
        raise RuntimeError(
            f"{provider_key} did not return a transaction split code for "
            f"order {order.order_number}."
        )
    return result.split_code, None, None


async def post_order_ledger_entries(db, order, payment_transaction, created_by: str) -> None:
    """Post the full settlement ledger for an order, per line item.

    For every order item this writes, in one ``entry_group_id``:
      - ``sale``      debit  platform_revenue   (gross line_total)
      - ``commission`` credit platform_revenue  (platform's cut, from the
        merchant's commission plan)
      - ``payout_hold`` credit merchant_wallet  (net = gross - commission,
        held until the merchant approves / the order is delivered)

    Used by the payment-success webhook AND the pay-on-delivery /
    proof-of-payment paths, so every paid order credits merchant wallets —
    multi-merchant orders simply produce one set of entries per merchant item.
    """
    group_id = uuid.uuid4()
    items_result = await db.execute(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )
    order_items = items_result.scalars().all()

    for item in order_items:
        gross = abs(item.line_total)
        plan = None
        merchant = (
            await db.execute(select(Merchant).where(Merchant.id == item.merchant_id))
        ).scalar_one_or_none()
        if merchant is not None:
            plan = (
                await db.execute(
                    select(CommissionPlan).where(
                        CommissionPlan.id == merchant.commission_plan_id
                    )
                )
            ).scalar_one_or_none()
        commission = compute_commission(gross, plan)
        net = gross - commission

        # Sale entry (debit — platform records the sale)
        db.add(
            LedgerEntry(
                entry_group_id=group_id,
                account_type="platform_revenue",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.DEBIT.value,
                entry_type=LedgerEntryType.SALE.value,
                amount=gross,
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(created_by),
            )
        )
        # Commission entry (credit — platform keeps its cut)
        if commission > 0:
            db.add(
                LedgerEntry(
                    entry_group_id=group_id,
                    account_type="platform_revenue",
                    merchant_id=item.merchant_id,
                    direction=LedgerDirection.CREDIT.value,
                    entry_type=LedgerEntryType.COMMISSION.value,
                    amount=commission,
                    currency=item.currency,
                    order_id=order.id,
                    payment_transaction_id=payment_transaction.id,
                    created_by=str(created_by),
                )
            )
        # Payout hold entry (credit — net funds held for the merchant until
        # approval/delivery, then released by a superseding payout_release)
        db.add(
            LedgerEntry(
                entry_group_id=group_id,
                account_type="merchant_wallet",
                merchant_id=item.merchant_id,
                direction=LedgerDirection.CREDIT.value,
                entry_type=LedgerEntryType.PAYOUT_HOLD.value,
                amount=net,
                currency=item.currency,
                order_id=order.id,
                payment_transaction_id=payment_transaction.id,
                created_by=str(created_by),
            )
        )


async def _create_payout_hold_entries(db, order, payment_transaction, created_by: str) -> None:
    """Back-compat wrapper — delegates to :func:`post_order_ledger_entries`.

    Mirrors the ledger entries in ``submit_proof_of_payment`` so that
    ``approve_order``'s payout-release balances against them.  Funds stay
    held until the merchant confirms pay-on-delivery payment.
    """
    await post_order_ledger_entries(db, order, payment_transaction, created_by)
