# app/modules/payments/service/implementation.py
"""
Concrete implementation of the payment service.
Handles database operations for payments using SQLAlchemy.
"""

import uuid

from app.core.security import to_uuid
from app.models.order import Order
from app.models.payment_transaction import PaymentTransaction
from app.models.webhook_event import WebhookEvent
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

        # Process payment with provider
        # In production, this would call the actual payment provider (Paystack, etc.)
        # and return the provider's authorization URL/reference.
        # For now, we create an "initialized" payment that the webhook will confirm.
        provider_reference = f"{payment_data.provider}_{uuid.uuid4()}"

        # Create payment transaction with "initialized" status
        # The webhook (not this endpoint) will update it to "success"
        payment_transaction = PaymentTransaction(
            order_id=order.id,
            provider=payment_data.provider,
            provider_reference=provider_reference,
            status="initialized",
            amount=order.total_amount,
            currency=order.currency,
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
        )

    async def list_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        order_id: str | None = None,
        status: str | None = None,
    ) -> list[PaymentResponse]:
        """
        List payments with optional filtering from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            order_id: Filter by order ID.
            status: Filter by payment status.
            
        Returns:
            List of payment responses.
        """
        query = select(PaymentTransaction)

        if order_id:
            query = query.where(PaymentTransaction.order_id == order_id)
        if status:
            query = query.where(PaymentTransaction.status == status)

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
        await self._db.commit()

        return WebhookResponse(
            status="success",
            message="Webhook received and stored",
            event_id=event_id,
        )
