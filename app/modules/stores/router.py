# app/modules/stores/router.py
"""
Stores router handling store-related operations.
Communicates with the service layer via the StoreService abstraction.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import get_current_active_user
from app.modules.stores.service.base import StoreService
from app.modules.stores.service.dependency import get_store_service
from app.schemas.store import StoreCreate, StoreResponse

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_store_service_depends = Depends(get_store_service)


@router.post("/", response_model=StoreResponse)
async def create_store(
    store_data: StoreCreate,
    current_user: dict = get_current_active_user_depends,
    service: StoreService = get_store_service_depends,
):
    """Create a new store."""
    # Check if user has permission (merchant owner or platform admin)
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        return await service.create_store(store_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=list[StoreResponse])
async def list_stores(
    current_user: dict = get_current_active_user_depends,
    service: StoreService = get_store_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    merchant_id: str | None = None,
):
    """List stores with optional filtering by merchant."""
    # Non-admin users can only see their own merchant's stores
    if current_user.role.value != "platform_admin":
        # TODO: Filter by user's merchant if needed
        pass

    return await service.list_stores(skip=skip, limit=limit, merchant_id=merchant_id)


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store(
    store_id: str,
    current_user: dict = get_current_active_user_depends,
    service: StoreService = get_store_service_depends,
):
    """Get a store by ID."""
    store = await service.get_store(store_id)

    if not store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        )

    return store


@router.get("/merchant/{merchant_id}", response_model=list[StoreResponse])
async def list_stores_by_merchant(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: StoreService = get_store_service_depends,
):
    """List all stores for a specific merchant."""
    return await service.list_stores_by_merchant(merchant_id)


# Include the router in the main app
def get_router():
    return router
