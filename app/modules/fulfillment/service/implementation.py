# app/modules/fulfillment/service/implementation.py
"""
Concrete implementation of the fulfillment service.
Handles database operations for fulfillment using SQLAlchemy.
"""


from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import to_uuid
from app.models.fulfillment import Fulfillment, FulfillmentStatus
from app.models.notification import NotificationChannel, NotificationType
from app.models.order import Order, OrderStatus
from app.modules.fulfillment.service.base import FulfillmentService
from app.modules.notifications.service.base import NotificationService
from app.schemas.fulfillment import (
    DigitalDeliveryUpdate,
    FulfillmentCreate,
    FulfillmentResponse,
    FulfillmentStatusUpdate,
    ShipmentUpdate,
)
from app.schemas.notification import NotificationCreate


class FulfillmentServiceImpl(FulfillmentService):
    """
    Database-backed implementation of FulfillmentService.

    This class encapsulates all database operations for fulfillment,
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
            ValueError: If order not found or not paid/accepted.
        """
        # Verify order exists
        result = await self._db.execute(
            select(Order).where(Order.id == to_uuid(fulfillment_data.order_id))
        )
        order = result.scalar_one_or_none()

        if not order:
            raise ValueError("Order not found")

        # Verify order is paid or accepted (merchant has accepted but not yet
        # shipped — a fulfillment record may be pre-created)
        if order.status not in (OrderStatus.PAID.value, OrderStatus.ACCEPTED.value):
            raise ValueError(
                f"Order must be paid or accepted to create fulfillment, current status: {order.status}"
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
            delivery_method=fulfillment_data.delivery_method,
            status=FulfillmentStatus.PENDING.value,
            carrier=fulfillment_data.carrier,
            tracking_number=fulfillment_data.tracking_number,
            download_token=fulfillment_data.download_token,
            dispute_window_ends=fulfillment_data.dispute_window_ends,
        )

        self._db.add(new_fulfillment)
        await self._db.commit()
        await self._db.refresh(new_fulfillment)

        # ── Notification: fulfillment created ───────────────────────────
        if self._notification_service:
            try:
                # Buyer: shipping update
                carrier_text = f" via {new_fulfillment.carrier}" if new_fulfillment.carrier else ""
                tracking_text = f" (tracking: {new_fulfillment.tracking_number})" if new_fulfillment.tracking_number else ""
                await self._notification_service.create_notification(
                    NotificationCreate(
                        user_id=str(order.buyer_id),
                        type=NotificationType.SHIPPING_UPDATE.value,
                        channel=NotificationChannel.EMAIL.value,
                        subject=f"Order {order.order_number} is being prepared",
                        body=(
                            f"Your order {order.order_number} has been handed off for fulfillment{carrier_text}{tracking_text}."
                        ),
                        related_order_id=str(order.id),
                    )
                )
            except Exception:
                pass

        return self._to_response(new_fulfillment)
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
            if fulfillment.status in (
                FulfillmentStatus.DELIVERED.value,
                FulfillmentStatus.DELIVERED_DIGITAL.value,
            ):
                from datetime import datetime as _dt
                fulfillment.delivered_at = _dt.now(UTC)

        await self._db.commit()
        await self._db.refresh(fulfillment)

        # ── Notification: shipping update ──────────────────────────────
        if self._notification_service and shipment_data.status is not None:
            try:
                from app.models.order import Order as _Order
                order_result = await self._db.execute(
                    select(_Order).where(_Order.id == fulfillment.order_id)
                )
                order = order_result.scalar_one_or_none()
                if order:
                    status_label = fulfillment.status.replace("_", " ").title()
                    carrier_text = f" via {fulfillment.carrier}" if fulfillment.carrier else ""
                    tracking_text = f" (tracking: {fulfillment.tracking_number})" if fulfillment.tracking_number else ""
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            user_id=str(order.buyer_id),
                            type=NotificationType.SHIPPING_UPDATE.value,
                            channel=NotificationChannel.EMAIL.value,
                            subject=f"Order {order.order_number} — {status_label}",
                            body=(
                                f"Your order {order.order_number} is now {status_label.lower()}{carrier_text}{tracking_text}."
                            ),
                            related_order_id=str(order.id),
                        )
                    )
                    # Check if all fulfillments are delivered → mark order fulfilled
                    await self._maybe_mark_order_fulfilled(order.id)
            except Exception:
                pass

        return self._to_response(fulfillment)

    async def _maybe_mark_order_fulfilled(self, order_id) -> None:
        """If all fulfillments for an order are delivered, mark the order fulfilled."""
        try:
            ff_result = await self._db.execute(
                select(Fulfillment).where(Fulfillment.order_id == order_id)
            )
            fulfillments = ff_result.scalars().all()
            if not fulfillments:
                return
            delivered_statuses = {
                FulfillmentStatus.DELIVERED.value,
                FulfillmentStatus.DELIVERED_DIGITAL.value,
            }
            if not all(f.status in delivered_statuses for f in fulfillments):
                return

            from app.models.order import Order as _Order
            from app.models.order import OrderStatus as _OrderStatus
            order = await self._db.get(_Order, order_id)
            if not order or order.status not in (
                _OrderStatus.PAID.value, _OrderStatus.SHIPPED.value,
            ):
                return
            order.status = _OrderStatus.FULFILLED.value
            from datetime import datetime as _dt
            order.fulfilled_at = _dt.now(UTC)
            await self._db.commit()

            # Notify buyer: order completed
            if self._notification_service:
                try:
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            user_id=str(order.buyer_id),
                            type=NotificationType.ORDER_COMPLETED.value,
                            channel=NotificationChannel.EMAIL.value,
                            subject=f"Order {order.order_number} completed",
                            body=(
                                f"Your order {order.order_number} has been delivered. "
                                f"Thank you for your purchase!"
                            ),
                            related_order_id=str(order.id),
                        )
                    )
                except Exception:
                    pass
        except Exception:
            pass

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
            if fulfillment.status in (
                FulfillmentStatus.DELIVERED.value,
                FulfillmentStatus.DELIVERED_DIGITAL.value,
            ):
                from datetime import datetime as _dt
                fulfillment.delivered_at = _dt.now(UTC)

        await self._db.commit()
        await self._db.refresh(fulfillment)

        # ── Notification: digital delivery ready ────────────────────────
        if self._notification_service and delivery_data.status is not None:
            try:
                from app.models.order import Order as _Order
                order_result = await self._db.execute(
                    select(_Order).where(_Order.id == fulfillment.order_id)
                )
                order = order_result.scalar_one_or_none()
                if order:
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            user_id=str(order.buyer_id),
                            type=NotificationType.DIGITAL_DELIVERY_READY.value,
                            channel=NotificationChannel.EMAIL.value,
                            subject=f"Your digital download is ready — Order {order.order_number}",
                            body=(
                                f"Your digital item for order {order.order_number} is ready for download. "
                                f"Use the download link provided in your order details."
                            ),
                            related_order_id=str(order.id),
                        )
                    )
                    await self._maybe_mark_order_fulfilled(order.id)
            except Exception:
                pass

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
        if fulfillment.status in (
            FulfillmentStatus.DELIVERED.value,
            FulfillmentStatus.DELIVERED_DIGITAL.value,
        ):
            from datetime import datetime as _dt
            fulfillment.delivered_at = _dt.now(UTC)

        await self._db.commit()
        await self._db.refresh(fulfillment)

        # ── Notification: shipping update ──────────────────────────────
        if self._notification_service:
            try:
                from app.models.order import Order as _Order
                order_result = await self._db.execute(
                    select(_Order).where(_Order.id == fulfillment.order_id)
                )
                order = order_result.scalar_one_or_none()
                if order:
                    status_label = fulfillment.status.replace("_", " ").title()
                    carrier_text = f" via {fulfillment.carrier}" if fulfillment.carrier else ""
                    tracking_text = f" (tracking: {fulfillment.tracking_number})" if fulfillment.tracking_number else ""
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            user_id=str(order.buyer_id),
                            type=NotificationType.SHIPPING_UPDATE.value,
                            channel=NotificationChannel.EMAIL.value,
                            subject=f"Order {order.order_number} — {status_label}",
                            body=(
                                f"Your order {order.order_number} is now {status_label.lower()}{carrier_text}{tracking_text}."
                            ),
                            related_order_id=str(order.id),
                        )
                    )
                    await self._maybe_mark_order_fulfilled(order.id)
            except Exception:
                pass

        return self._to_response(fulfillment)

    async def mark_delivered(
        self, fulfillment_id: str
    ) -> FulfillmentResponse:
        """
        Mark a shipped fulfillment as delivered.

        Transitions the fulfillment from 'shipped' to 'delivered', records
        the ``delivered_at`` timestamp, and (if all fulfillments for the
        order are now delivered) marks the parent order as 'fulfilled'.

        Args:
            fulfillment_id: The fulfillment ID to mark delivered.

        Returns:
            The updated fulfillment response.

        Raises:
            ValueError: If fulfillment not found or not in 'shipped' status.
        """
        result = await self._db.execute(
            select(Fulfillment).where(Fulfillment.id == to_uuid(fulfillment_id))
        )
        fulfillment = result.scalar_one_or_none()
        if not fulfillment:
            raise ValueError("Fulfillment not found")

        if fulfillment.status != FulfillmentStatus.SHIPPED.value:
            raise ValueError(
                f"Fulfillment must be in 'shipped' status to mark delivered, "
                f"current status: {fulfillment.status}"
            )

        fulfillment.status = FulfillmentStatus.DELIVERED.value
        from datetime import datetime as _dt
        fulfillment.delivered_at = _dt.now(UTC)

        await self._db.commit()
        await self._db.refresh(fulfillment)

        # ── Notification: delivery confirmation ──────────────────────────────
        if self._notification_service:
            try:
                from app.models.order import Order as _Order
                order_result = await self._db.execute(
                    select(_Order).where(_Order.id == fulfillment.order_id)
                )
                order = order_result.scalar_one_or_none()
                if order:
                    carrier_text = f" via {fulfillment.carrier}" if fulfillment.carrier else ""
                    tracking_text = f" (tracking: {fulfillment.tracking_number})" if fulfillment.tracking_number else ""
                    await self._notification_service.create_notification(
                        NotificationCreate(
                            user_id=str(order.buyer_id),
                            type=NotificationType.SHIPPING_UPDATE.value,
                            channel=NotificationChannel.EMAIL.value,
                            subject=f"Order {order.order_number} — Delivered",
                            body=(
                                f"Your order {order.order_number} has been delivered"
                                f"{carrier_text}{tracking_text}. Thank you for your purchase!"
                            ),
                            related_order_id=str(order.id),
                        )
                    )
                    await self._maybe_mark_order_fulfilled(order.id)
            except Exception:
                pass

        return self._to_response(fulfillment)

    @staticmethod
    def _to_response(fulfillment: Fulfillment) -> FulfillmentResponse:
        """Convert a Fulfillment model to FulfillmentResponse schema."""
        return FulfillmentResponse(
            id=str(fulfillment.id),
            order_id=str(fulfillment.order_id),
            merchant_id=str(fulfillment.merchant_id),
            type=fulfillment.type,
            delivery_method=fulfillment.delivery_method,
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
