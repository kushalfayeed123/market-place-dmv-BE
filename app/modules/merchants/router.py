# app/modules/merchants/router.py
"""
Merchants router handling merchant-related operations.
Communicates with the service layer via the MerchantService abstraction.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_active_user
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.schemas.merchants import MerchantCreate, MerchantResponse

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_merchant_service_depends = Depends(get_merchant_service)


@router.post("/", response_model=MerchantResponse)
async def create_merchant(
    merchant_data: MerchantCreate,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Create a new merchant."""
    # Only platform admins can create merchants directly
    if (
        current_user.role.value != "platform_admin"
        and current_user.role.value != "merchant_owner"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins can create merchants",
        )

    return await service.create_merchant(merchant_data)


@router.get("/", response_model=list[MerchantResponse])
async def list_merchants(
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
    skip: int = 0,
    limit: int = 100,
):
    """List merchants."""
    # Only platform admins can list all merchants
    if current_user.role.value != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins can list all merchants",
        )

    return await service.list_merchants(skip=skip, limit=limit)


@router.get("/{merchant_id}", response_model=MerchantResponse)
async def get_merchant(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Get merchant by ID."""
    merchant = await service.get_merchant(merchant_id)

    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found"
        )

    # Check permissions
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view this merchant",
        )

    return merchant


# Include the router in the main app
def get_router():
    return router
