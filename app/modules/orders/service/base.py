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
