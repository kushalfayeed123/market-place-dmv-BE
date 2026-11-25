# app/modules/notifications/router.py
"""
Notifications router.

Buyers can list their own notifications; merchants can list notifications
for orders in their store. The background worker calls `mark_sent` (internal)
via the service; the public API is read-only list/get plus a manual send
endpoint used by the worker.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user
from app.db.session import get_db
from app.modules.notifications.delivery import EmailNotificationSender
from app.modules.notifications.service.base import NotificationService
from app.modules.notifications.service.dependency import get_notification_service
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.schemas.notification import NotificationCreate, NotificationResponse

router = APIRouter()

get_current_active_user_depends = Depends(get_current_active_user)
get_notification_service_depends = Depends(get_notification_service)
get_merchant_service_depends = Depends(get_merchant_service)
get_db_depends = Depends(get_db)


@router.get("/me", response_model=list[NotificationResponse])
async def list_my_notifications(
    current_user= get_current_active_user_depends,
    service: NotificationService = get_notification_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None),
):
    """List notifications for the signed-in user."""
    return await service.list_user_notifications(
        str(current_user.id), skip=skip, limit=limit, status=status
    )


@router.get("/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: str,
    current_user= get_current_active_user_depends,
    service: NotificationService = get_notification_service_depends,
):
    """Get a single notification. Only the recipient owner may view it."""
    n = await service.get_notification(notification_id)
    if not n:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    if (
        str(current_user.id) != n.user_id
        and str(current_user.id) != n.merchant_id  # merchants see store-level notifications
        and current_user.role.value != "platform_admin"
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    return n


@router.post("/test-email", response_model=NotificationResponse)
async def send_test_email(
    current_user= get_current_active_user_depends,
    service: NotificationService = get_notification_service_depends,
    db: AsyncSession = get_db_depends,
):
    """Send a test email to the signed-in user via the Resend pipeline.

    Creates a templated ``test_email`` notification (queued for the worker)
    AND sends it immediately through the email sender so the caller gets
    instant confirmation that Resend is configured correctly.
    """
    from app.core.config import settings
    from app.models.user import User
    from sqlalchemy import select

    # Resolve the caller's email.
    user = (await db.execute(select(User).where(User.id == current_user.id))).scalar_one_or_none()
    if user is None or not user.email:
        raise HTTPException(status_code=404, detail="User email not found")

    # Queue a templated notification (worker will also deliver it).
    n = await service.notify(
        type="test_email",
        channel="email",
        user_id=str(current_user.id),
        context={"recipient_email": user.email},
    )

    # Send immediately for instant feedback.
    if not settings.RESEND_API_KEY or not settings.RESEND_FROM_EMAIL:
        raise HTTPException(
            status_code=400,
            detail="Resend is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL missing)",
        )
    try:
        receipt = await EmailNotificationSender().send(n, user.email)
        await service.mark_sent(n.id, receipt.provider, receipt.reference)
    except Exception as e:
        await service.mark_failed(n.id)
        raise HTTPException(status_code=502, detail=f"Email could not be sent: {e}")
    return await service.get_notification(n.id)


def get_router():
    return router
