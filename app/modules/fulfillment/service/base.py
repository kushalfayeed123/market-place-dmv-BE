# app/modules/fulfillment/service/base.py
"""
Abstract base class for fulfillment service.
Defines the interface that all fulfillment service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.fulfillment import (
    DigitalDeliveryUpdate,
    FulfillmentCreate,
    FulfillmentResponse,
    FulfillmentStatusUpdate,
    ShipmentUpdate,
)


class FulfillmentService(ABC):
    """
    Abstract interface for fulfillment operations.
    
    This class defines the contract for any fulfillment service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def create_fulfillment(
        self, fulfillment_data: FulfillmentCreate, merchant_id: str
    ) -> FulfillmentResponse:
        """
        Create a new fulfillment record.
        
        Args:
            fulfillment_data: The fulfillment data to create.
            merchant_id: The merchant ID from the order.
            
        Returns:
            The created fulfillment response.
            
        Raises:
            ValueError: If order not found or not paid.
        """
        ...

    @abstractmethod
    async def get_fulfillment(self, fulfillment_id: str) -> FulfillmentResponse | None:
        """
        Get a fulfillment by ID.
        
        Args:
            fulfillment_id: The fulfillment ID.
            
        Returns:
            The fulfillment response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_fulfillments_by_order(
        self, order_id: str
    ) -> list[FulfillmentResponse]:
        """
        List all fulfillments for an order.

        Args:
            order_id: The order ID.

        Returns:
            List of fulfillment responses.
        """
        ...

    @abstractmethod
    async def list_fulfillments_by_merchant(
        self,
        merchant_id: str,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FulfillmentResponse]:
        """
        List all fulfillments for a merchant.

        Args:
            merchant_id: The merchant ID.
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            status: Optional status filter.

        Returns:
            List of fulfillment responses.
        """
        ...

    @abstractmethod
    async def update_shipment(
        self, fulfillment_id: str, shipment_data: ShipmentUpdate
    ) -> FulfillmentResponse:
        """
        Update shipment details for a fulfillment.
        
        Args:
            fulfillment_id: The fulfillment ID.
            shipment_data: The shipment update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        ...

    @abstractmethod
    async def update_digital_delivery(
        self, fulfillment_id: str, delivery_data: DigitalDeliveryUpdate
    ) -> FulfillmentResponse:
        """
        Update digital delivery status.
        
        Args:
            fulfillment_id: The fulfillment ID.
            delivery_data: The digital delivery update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        ...

    @abstractmethod
    async def update_status(
        self, fulfillment_id: str, status_data: FulfillmentStatusUpdate
    ) -> FulfillmentResponse:
        """
        Update fulfillment status.
        
        Args:
            fulfillment_id: The fulfillment ID.
            status_data: The status update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        ...
