# app/modules/payments/router.py
"""
Payments router handling payment processing, refunds, and webhooks.
Communicates with the service layer via the PaymentService abstraction.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.security import get_current_active_user, to_uuid
from app.db.session import AsyncSession, get_db
from app.models.order import Order
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.modules.payments.service.base import PaymentService
from app.modules.payments.service.dependency import get_payment_service
from app.schemas.payments import (
    PaymentProcess,
    PaymentProviderInfo,
    PaymentResponse,
    RefundRequest,
    RefundResponse,
    WebhookPayload,
    WebhookResponse,
)

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_payment_service_depends = Depends(get_payment_service)
get_merchant_service_depends = Depends(get_merchant_service)


@router.post("/process", status_code=status.HTTP_201_CREATED, response_model=PaymentResponse)
async def process_payment(
    request: Request,
    payment_data: PaymentProcess,
    current_user: dict = get_current_active_user_depends,
    service: PaymentService = get_payment_service_depends,
    db: AsyncSession = Depends(get_db),
    idempotency: dict = get_idempotency_depends,
):
    """
    Process a payment for an order.
    Requires authentication, idempotency key, and appropriate permissions.
    """
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
        response_data = await service.process_payment(payment_data, str(current_user.id))
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=error_msg
            )
        if "not authorized" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=error_msg
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg
        )

    await finalize_idempotency(
        request, db, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.get("/", response_model=list[PaymentResponse])
async def list_payments(
    current_user: dict = get_current_active_user_depends,
    service: PaymentService = get_payment_service_depends,
    merchant_service: MerchantService = get_merchant_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    order_id: str | None = Query(None),
    status: str | None = Query(None),
    merchant_id: str | None = Query(None),
):
    """
    List payments with optional filtering.
    - Buyers see only their own order payments.
    - Merchants see payments for orders containing their items.
    - Platform admins see all payments.
    """
    # Determine merchant_id based on user role for access control
    resolved_merchant_id = merchant_id
    user_role = current_user.role.value
    if user_role == "merchant_owner" and not merchant_id:
        merchant = await merchant_service.get_merchant_by_owner(str(current_user.id))
        if merchant:
            resolved_merchant_id = str(merchant.id)

    return await service.list_payments(
        skip=skip,
        limit=limit,
        order_id=order_id,
        status=status,
        merchant_id=resolved_merchant_id,
    )


@router.get("/order/{order_id}", response_model=PaymentResponse)
async def get_payment_by_order(
    order_id: str,
    current_user: dict = get_current_active_user_depends,
    service: PaymentService = get_payment_service_depends,
):
    """Get the most recent payment for an order.
    Requires authentication — buyers can only see their own order's payments,
    merchants/admins can see payments for their orders.
    """
    try:
        payment = await service.get_payment_by_order(order_id, str(current_user.id))
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=error_msg
            )
        if "not authorized" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=error_msg
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg
        )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No payment found for this order",
        )

    return payment


@router.get("/methods", response_model=list[PaymentProviderInfo])
async def list_payment_methods(
    current_user: dict = get_current_active_user_depends,
    merchant_id: str | None = Query(None, description="Merchant ID to filter currency"),
    currency: str | None = Query(None, description="ISO 4217 currency to filter providers"),
):
    """List available payment providers.

    Returns all registered providers.  Providers that are declared but
    not yet implemented (e.g. Flutterwave, Stripe) are included with
    ``implemented=false`` and a ``disabled_reason`` so the frontend can
    render them as disabled buttons.

    The ``currency`` query parameter filters the list to providers that
    support a given currency.
    """
    from app.modules.payments.providers.registry import get_available_providers

    providers = get_available_providers(currency)

    # Pay on Delivery is a merchant-confirmed payment method, not an online
    # provider, so it is not in the provider registry.  It is always shown as
    # an available (implemented) option for every currency.
    providers = [
        *providers,
        PaymentProviderInfo(
            key="pay_on_delivery",
            name="Pay on Delivery",
            implemented=True,
            supported_currencies=["NGN", "USD", "GBP", "EUR", "KES", "ZAR"],
        ),
    ]
    return [
        PaymentProviderInfo(
            key=p.key,
            name=p.name,
            implemented=p.implemented,
            supported_currencies=p.supported_currencies,
            disabled_reason=None if p.implemented else "Provider not yet integrated",
        )
        for p in providers
    ]


@router.post("/{payment_id}/refund", response_model=RefundResponse)
async def process_refund(
    request: Request,
    payment_id: str,
    refund_data: RefundRequest,
    current_user: dict = get_current_active_user_depends,
    service: PaymentService = get_payment_service_depends,
    db: AsyncSession = Depends(get_db),
    idempotency: dict = get_idempotency_depends,
):
    """
    Process a refund for a payment.
    Requires platform admin or merchant owner role.
    """
    # Check if idempotency short-circuit is active (cached response)
    if getattr(request.state, 'skip_execution', False):
        cached = getattr(request.state, 'cached_response', None)
        if cached:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=cached["status_code"],
                content=cached["body"],
            )

    # Check permissions
    if current_user.role.value not in ["platform_admin", "merchant_owner", "merchant_staff"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins and merchants can process refunds",
        )

    try:
        response_data = await service.process_refund(payment_id, refund_data)
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
        request, db, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.post("/webhooks/{provider}", response_model=WebhookResponse)
async def handle_webhook(
    request: Request,
    provider: str,
    webhook_payload: WebhookPayload,
    service: PaymentService = get_payment_service_depends,
):
    """
    Handle incoming webhooks from payment providers.
    Verifies signature and processes idempotently.
    """
    # Use the parsed model directly
    payload = webhook_payload.model_dump()
    
    # Extract event details from payload
    event_type = payload.get("event")
    event_id = payload.get("data", {}).get("id") or payload.get("data", {}).get("reference")
    
    if not event_type or not event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required event fields",
        )
    
    # Get raw body if needed for signature verification
    body = await request.body()
    
    return await service.handle_webhook(provider, event_type, event_id, body)


@router.post("/stub/simulate", response_model=WebhookResponse)
async def simulate_payment_callback(
    ref: str = Query(..., description="Provider reference from the stub redirect URL"),
    service: PaymentService = get_payment_service_depends,
):
    """Simulate a successful Paystack callback (dev/test only).

    When the Paystack provider runs in stub mode the ``payment_url`` points to a
    frontend callback page that calls this endpoint.  This fires a simulated
    ``charge.success`` webhook so the full checkout → pay → confirm cycle works
    end-to-end without real API keys.
    """
    import json as _json
    payload = _json.dumps({
        "event": "charge.success",
        "data": {"id": f"stub_evt_{ref}", "reference": ref},
    }).encode("utf-8")
    return await service.handle_webhook("paystack", "charge.success", f"stub_evt_{ref}", payload)


# ── Dynamic /{payment_id} routes go LAST so they don't shadow static paths ────

@router.get("/{payment_id}", response_model=PaymentResponse)
async def get_payment(
    payment_id: str,
    current_user: dict = get_current_active_user_depends,
    service: PaymentService = get_payment_service_depends,
):
    """Get payment details by ID. Requires authentication."""
    payment = await service.get_payment(payment_id)

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    # Authorization check: buyer can only see their own order's payment
    # merchant/admin can see payments for their orders
    order_result = await service._db.execute(
        select(Order).where(Order.id == to_uuid(payment.order_id))
    )
    order = order_result.scalar_one_or_none()

    if order:
        user_role = current_user.role.value
        user_id = str(current_user.id)
        is_owner = order.buyer_id == to_uuid(user_id)
        is_merchant = user_role in ["merchant_owner", "merchant_staff", "platform_admin"]

        if not is_owner and not is_merchant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this payment",
            )

    return payment


# Include the router in the main app
def get_router():
    return router
