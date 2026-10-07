# app/modules/merchants/router.py
"""
Merchants router handling merchant-related operations.
Communicates with the service layer via the MerchantService abstraction.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import get_current_active_user
from app.modules.merchants.service.base import MerchantService
from app.modules.merchants.service.dependency import get_merchant_service
from app.modules.stores.service.base import StoreService
from app.modules.stores.service.dependency import get_store_service
from app.schemas.merchants import (
    MerchantCreate,
    MerchantOnboard,
    MerchantPayoutAccountCreate,
    MerchantPayoutAccountResponse,
    MerchantPayoutAccountUpdate,
    MerchantResponse,
    MerchantUpdate,
)
from app.schemas.store import StoreCreate

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_merchant_service_depends = Depends(get_merchant_service)
get_store_service_depends = Depends(get_store_service)


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


@router.post("/onboard", response_model=MerchantResponse)
async def onboard_merchant(
    merchant_data: MerchantOnboard,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
    store_service: StoreService = get_store_service_depends,
):
    """
    Self-service onboarding for the authenticated ``merchant_owner``.

    Creates a merchant (and primary store) record for the current user.
    The ``owner_user_id`` and ``commission_plan_id`` are derived
    server-side so the client never supplies them.
    """
    if current_user.role.value != "merchant_owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only merchant owners can onboard a merchant",
        )

    try:
        merchant = await service.create_merchant_for_user(
            str(current_user.id), merchant_data
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return merchant


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


@router.get("/{merchant_id}", response_model=MerchantResponse)
async def get_merchant(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Get a merchant by ID."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Merchant not found",
        )
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this merchant",
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
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this merchant",
        )
    return await service.update_merchant(merchant_id, merchant_data)


# --- Payout account endpoints ---


@router.post(
    "/{merchant_id}/payout-accounts", response_model=MerchantPayoutAccountResponse
)
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
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await service.create_payout_account(merchant_id, data)


@router.get(
    "/{merchant_id}/payout-accounts", response_model=list[MerchantPayoutAccountResponse]
)
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
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    return await service.list_payout_accounts(merchant_id, skip=skip, limit=limit)


@router.get(
    "/{merchant_id}/payout-accounts/{payout_id}",
    response_model=MerchantPayoutAccountResponse,
)
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


@router.put(
    "/{merchant_id}/payout-accounts/{payout_id}",
    response_model=MerchantPayoutAccountResponse,
)
async def update_payout_account(
    merchant_id: str,
    payout_id: str,
    data: MerchantPayoutAccountUpdate,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Update a payout account for a merchant."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        return await service.update_payout_account(merchant_id, payout_id, data)
    except ValueError:
        raise HTTPException(status_code=404, detail="Payout account not found")


@router.delete(
    "/{merchant_id}/payout-accounts/{payout_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_payout_account(
    merchant_id: str,
    payout_id: str,
    current_user: dict = get_current_active_user_depends,
    service: MerchantService = get_merchant_service_depends,
):
    """Deactivate (soft-delete) a payout account."""
    merchant = await service.get_merchant(merchant_id)
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")
    if current_user.role.value != "platform_admin" and merchant.owner_user_id != str(
        current_user.id
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    try:
        await service.delete_payout_account(merchant_id, payout_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Payout account not found")
    return None


# Include the router in the main app
def get_router():
    return router
