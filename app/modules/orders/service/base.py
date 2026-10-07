# app/modules/orders/service/base.py
"""
Abstract base class for order service.
Defines the interface that all order service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.orders import (
    CheckoutRequest,
    CheckoutResponse,
    OrderResponse,
    ProofOfPaymentRequest,
    ProofOfPaymentResponse,
    OrderApprovalResponse,
)


class OrderService(ABC):
    """
    Abstract interface for order operations.
    
    This class defines the contract for any order service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def checkout(
        self, checkout_data: CheckoutRequest, buyer_id: str, idempotency_key: str
    ) -> CheckoutResponse:
        """
        Process checkout and create an order.
        
        Args:
            checkout_data: The checkout request data.
            buyer_id: The buyer's user ID.
            idempotency_key: The idempotency key for the order.
            
        Returns:
            The checkout response with order details.
            
        Raises:
            ValueError: If cart items are invalid or inventory insufficient.
        """
        ...

    @abstractmethod
    async def get_order(self, order_id: str) -> OrderResponse | None:
        """
        Get an order by ID with its items.
        
        Args:
            order_id: The order ID.
            
        Returns:
            The order response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_orders(
        self,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> list[OrderResponse]:
        """
        List orders with optional filtering.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            status: Filter by order status.
            user_id: Current user ID for access control.
            user_role: Current user role for access control.
            
        Returns:
            List of order responses.
        """
        ...

    @abstractmethod
    async def submit_proof_of_payment(
        self,
        order_id: str,
        buyer_id: str,
        proof_data: ProofOfPaymentRequest,
    ) -> ProofOfPaymentResponse:
        """
        Record proof of payment for an order (offline / bank transfer).

        Creates a PaymentTransaction with status 'pending_verification',
        a hold ledger entry, and transitions the order to
        'awaiting_approval'.

        Args:
            order_id: The order ID.
            buyer_id: The buyer's user ID (must own the order).
            proof_data: Proof-of-payment payload (image URL, provider, reference).

        Returns:
            Proof-of-payment response with the new status.

        Raises:
            ValueError: If the order is not found, not owned by the buyer,
                        or already has a pending proof.
        """
        ...

    @abstractmethod
    async def approve_order(
        self,
        order_id: str,
        merchant_id: str,
    ) -> OrderApprovalResponse:
        """
        Merchant approves an order that has proof of payment on file.

        Transitions the order to 'paid', creates the payout-release ledger
        entry, and notifies the buyer.

        Args:
            order_id: The order ID.
            merchant_id: The merchant's ID (must own the order items).

        Returns:
            Approval response with the new status.

        Raises:
            ValueError: If the order is not found, not owned by the merchant,
                        or not in 'awaiting_approval' status.
        """
        ...
