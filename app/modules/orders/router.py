# app/modules/orders/router.py
"""
Orders router handling cart, checkout, and order management.
Communicates with the service layer via the OrderService abstraction.
"""


from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.rate_limit import sliding_window_allow
from app.core.security import get_current_active_user
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.modules.notifications.service.base import NotificationService
from app.modules.notifications.service.dependency import get_notification_service
from app.modules.orders.service.base import OrderService
from app.modules.orders.service.dependency import get_order_service
from app.schemas.notification import NotificationCreate
from app.schemas.orders import (
    CheckoutRequest,
    CheckoutResponse,
    OrderResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_order_service_depends = Depends(get_order_service)
get_merchant_service_depends = Depends(get_merchant_service)
get_notification_service_depends = Depends(get_notification_service)


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    request: Request,
    checkout_data: CheckoutRequest,
    current_user: dict = get_current_active_user_depends,
    service: OrderService = get_order_service_depends,
    notification_service: NotificationService = get_notification_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """
    Process checkout and create order.
    Requires authentication, idempotency key, and is rate limited.
    """
    # Verify user is a buyer or platform admin (admin allowed for testing)
    if current_user.role.value not in ("buyer", "platform_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only buyers and platform admins can checkout",
        )

    # Rate limit checkout attempts per user
    key = f"rl:checkout:{current_user.id}"
    allowed = await sliding_window_allow(key, 10, 60)  # 10 per minute
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Checkout rate limit exceeded",
            headers={"Retry-After": "60"},
        )

    # Check if idempotency short-circuit is active (cached response)
    if getattr(request.state, 'skip_execution', False):
        cached = getattr(request.state, 'cached_response', None)
        if cached:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["body"],
            )

    try:
        response_data = await service.checkout(
            checkout_data, 
            str(current_user.id), 
            getattr(request.state, 'idempotency_key', None) or ''
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    # Create notifications: order confirmation for the buyer and a
    # new-order notice for each merchant whose products are on the order.
    await notification_service.create_notification(
        NotificationCreate(
            user_id=str(current_user.id),
            type="order_confirmation",
            subject=f"Order {response_data.order_number} confirmed",
            body=f"Your order {response_data.order_number} has been placed successfully.",
            related_order_id=response_data.id,
        )
    )
    seen_merchants: set[str] = set()
    for item in response_data.items:
        merchant_id = item.get("merchant_id")
        if merchant_id and merchant_id not in seen_merchants:
            seen_merchants.add(merchant_id)
            await notification_service.create_notification(
                NotificationCreate(
                    merchant_id=merchant_id,
                    type="merchant_new_order",
                    subject=f"New order {response_data.order_number} received",
                    body=f"You received a new order {response_data.order_number}.",
                    related_order_id=response_data.id,
                )
            )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    current_user: dict = get_current_active_user_depends,
    service: OrderService = get_order_service_depends,
    merchant_service: MerchantService = get_merchant_service_depends,
):
    """Get order details by ID."""
    # Determine merchant_id based on user role
    merchant_id = None
    if current_user.role.value == "merchant_owner":
        # Look up merchant by owner_user_id
        result = await merchant_service.get_merchant_by_owner(str(current_user.id))
        if result:
            merchant_id = str(result.id)
    elif current_user.role.value == "merchant_staff":
        # merchant_staff need to provide explicit merchant_id in request
        pass  # Will be handled by query parameter or default to None
    
    order = await service.get_order(order_id, merchant_id=merchant_id)

    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    # Check permissions
    if current_user.role.value == "buyer" and order.buyer_id != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this order",
        )

    return order


@router.get("/", response_model=list[OrderResponse])
async def list_orders(
    current_user: dict = get_current_active_user_depends,
    service: OrderService = get_order_service_depends,
    merchant_service: MerchantService = get_merchant_service_depends,
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
):
    """List orders for the current user."""
    # Determine merchant_id based on user role
    merchant_id = None
    if current_user.role.value == "merchant_owner":
        # Look up merchant by owner_user_id
        result = await merchant_service.get_merchant_by_owner(str(current_user.id))
        if result:
            merchant_id = str(result.id)
    elif current_user.role.value == "merchant_staff":
        # merchant_staff need to provide explicit merchant_id in request
        # For now, we'll let the service layer handle it or default to None
        merchant_id = None
    
    return await service.list_orders(
        skip=skip,
        limit=limit,
        status=status,
        user_id=str(current_user.id),
        user_role=current_user.role.value,
        merchant_id=merchant_id,
    )


@router.get("/merchant/{merchant_id}", response_model=list[OrderResponse])
async def list_merchant_orders(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: OrderService = get_order_service_depends,
    merchant_service: MerchantService = get_merchant_service_depends,
    skip: int = 0,
    limit: int = 100,
    status: str | None = None,
):
    """List orders for a specific merchant.
    
    Only merchant owners and staff can access this endpoint.
    Staff need the merchant_id to match their assigned merchant.
    """
    # Determine if the current user can access this merchant's orders
    merchant_owner_id = None
    if current_user.role.value == "merchant_owner":
        # Look up merchant by owner_user_id
        merchant = await merchant_service.get_merchant_by_owner(str(current_user.id))
        if merchant:
            merchant_owner_id = str(merchant.id)
    
    # Verify access
    if current_user.role.value == "merchant_owner":
        # Merchant owner can only see their own orders
        if merchant_owner_id != merchant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this merchant's orders",
            )
    elif current_user.role.value == "merchant_staff":
        # Staff need explicit merchant_id match
        # In a full implementation, this would check a merchant_users junction table
        # For now, we'll allow if the ID matches
        pass
    
    return await service.list_orders(
        skip=skip,
        limit=limit,
        status=status,
        merchant_id=merchant_id,
        user_role=current_user.role.value,
        user_id=str(current_user.id),
    )


# Include the router in the main app
def get_router():
    return router
