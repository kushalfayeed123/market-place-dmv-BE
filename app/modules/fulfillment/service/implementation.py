# app/modules/fulfillment/service/implementation.py
"""
Concrete implementation of the fulfillment service.
Handles database operations for fulfillment using SQLAlchemy.
"""


from app.core.security import to_uuid
from app.models.fulfillment import Fulfillment, FulfillmentStatus
from app.models.order import Order, OrderStatus
from app.modules.fulfillment.service.base import FulfillmentService
from app.schemas.fulfillment import (
    DigitalDeliveryUpdate,
    FulfillmentCreate,
    FulfillmentResponse,
    FulfillmentStatusUpdate,
    ShipmentUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class FulfillmentServiceImpl(FulfillmentService):
    """
    Database-backed implementation of FulfillmentService.
    
    This class encapsulates all database operations for fulfillment,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def create_fulfillment(
        self, fulfillment_data: FulfillmentCreate, merchant_id: str | None = None
    ) -> FulfillmentResponse:
        """
        Create a new fulfillment record in the database.
        
        Args:
            fulfillment_data: The fulfillment data to create.
            merchant_id: The merchant ID from the order.
            
        Returns:
            The created fulfillment response.
            
        Raises:
            ValueError: If order not found or not paid.
        """
        # Verify order exists
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(fulfillment_data.order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise ValueError("Order not found")

        # Verify order is paid
        if order.status != OrderStatus.PAID.value:
            raise ValueError(
                f"Order must be paid to create fulfillment, current status: {order.status}"
            )

        # Verify merchant owns items in this order
        if merchant_id is not None:
            from app.models.order_item import OrderItem
            
            # Check if order has items belonging to this merchant
            result = await self._db.execute(
                select(OrderItem).where(
                    OrderItem.order_id == order.id,
                    OrderItem.merchant_id == to_uuid(merchant_id)
                )
            )
            merchant_items = result.scalars().all()
            
            if not merchant_items:
                raise ValueError(
                    f"Order does not contain items for merchant {merchant_id}"
                )
        
        new_fulfillment = Fulfillment(
            order_id=order.id,
            merchant_id=to_uuid(merchant_id) if merchant_id else None,
            type=fulfillment_data.type.value,
            status=FulfillmentStatus.PENDING.value,
            carrier=fulfillment_data.carrier,
            tracking_number=fulfillment_data.tracking_number,
            download_token=fulfillment_data.download_token,
            dispute_window_ends=fulfillment_data.dispute_window_ends,
        )

        self._db.add(new_fulfillment)
        await self._db.commit()
        await self._db.refresh(new_fulfillment)

        return self._to_response(new_fulfillment)

    async def get_fulfillment(self, fulfillment_id: str | None = None) -> FulfillmentResponse | None:
        """
        Get a fulfillment by ID from the database.
        
        Args:
            fulfillment_id: The fulfillment ID.
            
        Returns:
            The fulfillment response if found, None otherwise.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == to_uuid(fulfillment_id))
        )
        fulfillment = result.scalar_one_or_none()

        if fulfillment is None:
            return None

        return self._to_response(fulfillment)

    async def list_fulfillments_by_order(
        self, order_id: str
    ) -> list[FulfillmentResponse]:
        """
        List all fulfillments for an order from the database.
        
        Args:
            order_id: The order ID.
            
        Returns:
            List of fulfillment responses.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.order_id == to_uuid(order_id))
        )
        fulfillments = result.scalars().all()

        return [self._to_response(fulfillment) for fulfillment in fulfillments]

    async def list_fulfillments_by_merchant(
        self,
        merchant_id: str,
        skip: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[FulfillmentResponse]:
        """
        List all fulfillments for a merchant from the database.

        Args:
            merchant_id: The merchant ID.
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            status: Optional status filter.

        Returns:
            List of fulfillment responses.
        """
        query = select(Fulfillment).where(Fulfillment.merchant_id == to_uuid(merchant_id))
        if status:
            query = query.where(Fulfillment.status == status)
        query = query.offset(skip).limit(limit)
        result = await self._db.execute(query)
        fulfillments = result.scalars().all()
        return [self._to_response(fulfillment) for fulfillment in fulfillments]

    async def update_shipment(
        self, shipment_data: ShipmentUpdate, fulfillment_id: str | None = None
    ) -> FulfillmentResponse:
        """
        Update shipment details for a fulfillment in the database.
        
        Args:
            fulfillment_id: The fulfillment ID.
            shipment_data: The shipment update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == to_uuid(fulfillment_id))
        )
        fulfillment = result.scalar_one_or_none()

        if not fulfillment:
            raise ValueError("Fulfillment not found")

        if shipment_data.carrier is not None:
            fulfillment.carrier = shipment_data.carrier
        if shipment_data.tracking_number is not None:
            fulfillment.tracking_number = shipment_data.tracking_number
        if shipment_data.status is not None:
            fulfillment.status = shipment_data.status.value

        await self._db.commit()
        await self._db.refresh(fulfillment)

        return self._to_response(fulfillment)

    async def update_digital_delivery(
        self, delivery_data: DigitalDeliveryUpdate, fulfillment_id: str | None = None
    ) -> FulfillmentResponse:
        """
        Update digital delivery status in the database.
        
        Args:
            fulfillment_id: The fulfillment ID.
            delivery_data: The digital delivery update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == to_uuid(fulfillment_id))
        )
        fulfillment = result.scalar_one_or_none()

        if not fulfillment:
            raise ValueError("Fulfillment not found")

        if delivery_data.downloads_used is not None:
            fulfillment.downloads_used = delivery_data.downloads_used
        if delivery_data.status is not None:
            fulfillment.status = delivery_data.status.value

        await self._db.commit()
        await self._db.refresh(fulfillment)

        return self._to_response(fulfillment)

    async def update_status(
        self, status_data: FulfillmentStatusUpdate, fulfillment_id: str | None = None
    ) -> FulfillmentResponse:
        """
        Update fulfillment status in the database.
        
        Args:
            fulfillment_id: The fulfillment ID.
            status_data: The status update data.
            
        Returns:
            The updated fulfillment response.
            
        Raises:
            ValueError: If fulfillment not found.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == to_uuid(fulfillment_id))
        )
        fulfillment = result.scalar_one_or_none()

        if not fulfillment:
            raise ValueError("Fulfillment not found")

        fulfillment.status = status_data.status.value

        await self._db.commit()
        await self._db.refresh(fulfillment)

        return self._to_response(fulfillment)

    @staticmethod
    def _to_response(fulfillment: Fulfillment) -> FulfillmentResponse:
        """Convert a Fulfillment model to FulfillmentResponse schema."""
        return FulfillmentResponse(
            id=str(fulfillment.id),
            order_id=str(fulfillment.order_id),
            merchant_id=str(fulfillment.merchant_id),
            type=fulfillment.type,
            status=fulfillment.status,
            carrier=fulfillment.carrier,
            tracking_number=fulfillment.tracking_number,
            download_token=fulfillment.download_token,
            downloads_used=fulfillment.downloads_used,
            delivered_at=fulfillment.delivered_at,
            dispute_window_ends=fulfillment.dispute_window_ends,
            created_at=fulfillment.created_at,
            updated_at=fulfillment.updated_at,
        )
