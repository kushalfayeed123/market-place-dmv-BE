# app/modules/payments/service/base.py
"""
Abstract base class for payment service.
Defines the interface that all payment service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.payments import (
    PaymentProcess,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
    WebhookResponse,
)


class PaymentService(ABC):
    """
    Abstract interface for payment operations.
    
    This class defines the contract for any payment service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def process_payment(
        self, payment_data: PaymentProcess, user_id: str
    ) -> PaymentResponse:
        """
        Process a payment for an order.
        
        Args:
            payment_data: The payment processing data.
            user_id: The user ID initiating the payment.
            
        Returns:
            The payment response.
            
        Raises:
            ValueError: If order not found or not authorized.
        """
        ...

    @abstractmethod
    async def get_payment(self, payment_id: str) -> PaymentResponse | None:
        """
        Get a payment by ID.
        
        Args:
            payment_id: The payment ID.
            
        Returns:
            The payment response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_payments(
        self,
        skip: int = 0,
        limit: int = 100,
        order_id: str | None = None,
        status: str | None = None,
        merchant_id: str | None = None,
    ) -> list[PaymentResponse]:
        """
        List payments with optional filtering.

        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            order_id: Filter by order ID.
            status: Filter by payment status.
            merchant_id: Filter by merchant (joins through Order → OrderItem).

        Returns:
            List of payment responses.
        """
        ...

    @abstractmethod
    async def process_refund(
        self, payment_id: str, refund_data: RefundRequest
    ) -> RefundResponse:
        """
        Process a refund for a payment.
        
        Args:
            payment_id: The payment ID to refund.
            refund_data: The refund request data.
            
        Returns:
            The refund response.
            
        Raises:
            ValueError: If payment not found or already refunded.
        """
        ...

    @abstractmethod
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
        ...
