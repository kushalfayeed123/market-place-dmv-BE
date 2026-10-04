# app/modules/fulfillment/router.py
"""
Fulfillment router handling shipments and digital deliveries.
Communicates with the service layer via the FulfillmentService abstraction.
"""


from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.security import get_current_active_user
from app.models.order import Order
from app.models.order_item import OrderItem
from app.modules.fulfillment.service.base import FulfillmentService
from app.modules.fulfillment.service.dependency import get_fulfillment_service
from app.schemas.fulfillment import (
    DigitalDeliveryUpdate,
    FulfillmentCreate,
    FulfillmentResponse,
    FulfillmentStatusUpdate,
    ShipmentUpdate,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_fulfillment_service_depends = Depends(get_fulfillment_service)

# --- list fulfillments (must come before /{fulfillment_id} route) ---


@router.get("/", response_model=list[FulfillmentResponse])
async def list_fulfillments(
    request: Request,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    merchant_id: str | None = Query(None),
    status: str | None = Query(None),
):
    """List fulfillments for the current merchant (or by merchant_id for admins)."""
    resolved_merchant_id = merchant_id
    user_role = current_user.role.value

    if user_role == "merchant_owner" and not merchant_id:
        from app.modules.merchants.service.dependency import get_merchant_service
        merchant_service = get_merchant_service()
        merchant = await merchant_service.get_merchant(str(current_user.id))
        if merchant:
            resolved_merchant_id = str(merchant.id)

    if resolved_merchant_id is None and user_role != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Merchant ID required for your role",
        )

    return await service.list_fulfillments_by_merchant(
        merchant_id=resolved_merchant_id,
        skip=skip,
        limit=limit,
        status=status,
    )


@router.post("/", response_model=FulfillmentResponse)
async def create_fulfillment(
    request: Request,
    fulfillment_data: FulfillmentCreate,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """
    Create a fulfillment record for an order.
    Typically called after payment is processed.
    """
    # Check permissions based on user role
    if current_user.role.value == "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers cannot create fulfillments",
        )

    try:
        # In practice, merchant_id would be derived from the order
        # merchant_id = current_user.role.value if current_user.role.value != "buyer" else None
        response_data = await service.create_fulfillment(fulfillment_data, str(current_user.id))
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=error_msg
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.get("/{fulfillment_id}", response_model=FulfillmentResponse)
async def get_fulfillment(
    fulfillment_id: str,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
):
    """Get fulfillment details by ID."""
    # Check permissions based on user role
    if current_user.role.value == "buyer":
        # Buyers can only see fulfillments for orders they purchased
        fulfillment = await service.get_fulfillment(fulfillment_id)
        if not fulfillment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fulfillment not found",
            )
        # Verify the order belongs to the buyer
        order_result = await service._db.execute(
            select(Order).where(Order.id == fulfillment.order_id)
        )
        order = order_result.scalar_one_or_none()
        if not order or order.buyer_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this fulfillment",
            )
    elif current_user.role.value in ("merchant_owner", "merchant_staff"):
        # Merchants can only see their own fulfillments
        fulfillment = await service.get_fulfillment(fulfillment_id)
        if not fulfillment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Fulfillment not found",
            )
        # Verify the fulfillment belongs to the merchant's order
        if fulfillment.merchant_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this fulfillment",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view fulfillment",
        )
    
    return fulfillment


@router.get("/order/{order_id}", response_model=list[FulfillmentResponse])
async def list_fulfillments_by_order(
    order_id: str,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
):
    """List all fulfillments for a specific order."""
    # Check permissions based on user role
    if current_user.role.value == "buyer":
        # Buyers can only see fulfillments for orders they purchased
        # First verify the order belongs to the buyer
        result = await service._db.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order or order.buyer_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view fulfillments for this order",
            )
        # Now get fulfillments for this order
        return await service.list_fulfillments_by_order(order_id)
    
    elif current_user.role.value in ("merchant_owner", "merchant_staff"):
        # Merchants can only see their own fulfillments for this order
        # First verify the order has items belonging to the merchant
        from sqlalchemy import select

        result = await service._db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        order_items = result.scalars().all()
        
        # Check if any items belong to this merchant
        # For merchant_owner, check if owner_user_id matches
        # For merchant_staff, we need explicit merchant_id verification
        if current_user.role.value == "merchant_owner":
            # Look up merchant by owner_user_id
            from app.modules.merchants.service.dependency import get_merchant_service
            merchant_service = get_merchant_service()
            merchant = await merchant_service.get_merchant(str(current_user.id))
            if not merchant:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Merchant not found",
                )
            # Check if order has items for this merchant
            merchant_items = [item for item in order_items if str(item.merchant_id) == str(merchant.id)]
            if not merchant_items:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="No items found for this merchant in the order",
                )
        # Get fulfillments for this order
        return await service.list_fulfillments_by_order(order_id)
    
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view fulfillments",
        )


@router.put("/{fulfillment_id}/shipment", response_model=FulfillmentResponse)
async def update_shipment(
    fulfillment_id: str,
    shipment_data: ShipmentUpdate,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
):
    """Update shipment details for a fulfillment."""
    # Check permissions
    if current_user.role.value == "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers cannot update shipments",
        )

    try:
        response_data = await service.update_shipment(fulfillment_id, shipment_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    return response_data


@router.put("/{fulfillment_id}/digital-delivery", response_model=FulfillmentResponse)
async def update_digital_delivery(
    fulfillment_id: str,
    delivery_data: DigitalDeliveryUpdate,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
):
    """Update digital delivery status."""
    # Check permissions
    if current_user.role.value == "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers cannot update digital deliveries",
        )

    try:
        response_data = await service.update_digital_delivery(fulfillment_id, delivery_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    return response_data


@router.put("/{fulfillment_id}/status", response_model=FulfillmentResponse)
async def update_status(
    fulfillment_id: str,
    status_data: FulfillmentStatusUpdate,
    current_user: dict = get_current_active_user_depends,
    service: FulfillmentService = get_fulfillment_service_depends,
):
    """Update fulfillment status."""
    # Check permissions
    if current_user.role.value == "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Buyers cannot update fulfillment status",
        )

    try:
        response_data = await service.update_status(fulfillment_id, status_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    return response_data


# Include the router in the main app
def get_router():
    return router
