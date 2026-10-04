# app/modules/merchants/router.py
"""
Merchants router handling merchant-related operations.
Communicates with the service layer via the MerchantService abstraction.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_active_user
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.schemas.merchants import (
    MerchantCreate,
    MerchantResponse,
    MerchantUpdate,
    MerchantPayoutAccountCreate,
    MerchantPayoutAccountResponse,
    MerchantPayoutAccountUpdate,
)

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


@router.get("/by-owner/{user_id}", response_model=MerchantResponse)
async def get_merchant_by_owner(
    user_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Get the merchant owned by a specific user."""
    merchant = await service.get_merchant_by_owner(user_id)
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Merchant not found for this user",
        )
    return merchant


@router.put("/{merchant_id}", response_model=MerchantResponse)
async def update_merchant(
    merchant_id: str,
    merchant_data: MerchantUpdate,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Update a merchant's information (partial)."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Merchant not found"
        )
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this merchant",
        )
    return await service.update_merchant(merchant_id, merchant_data)


# --- Payout account endpoints ---


@router.post("/{merchant_id}/payout-accounts", response_model=MerchantPayoutAccountResponse)
async def create_payout_account(
    merchant_id: str,
    data: MerchantPayoutAccountCreate,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Create a payout account for a merchant."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await service.create_payout_account(merchant_id, data)


@router.get("/{merchant_id}/payout-accounts", response_model=list[MerchantPayoutAccountResponse])
async def list_payout_accounts(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
    skip: int = 0,
    limit: int = 100,
):
    """List payout accounts for a merchant."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await service.list_payout_accounts(merchant_id, skip=skip, limit=limit)


@router.get("/{merchant_id}/payout-accounts/{payout_id}", response_model=MerchantPayoutAccountResponse)
async def get_payout_account(
    merchant_id: str,
    payout_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Get a specific payout account."""
    account = await service.get_payout_account(merchant_id, payout_id)
    if not account:
        raise HTTPException(status_code=404, detail="Payout account not found")
    return account


# Include the router in the main app
def get_router():
    return router
