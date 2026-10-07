# app/modules/ledger/router.py
"""
Ledger router for viewing financial ledger entries and balances.
Communicates with the service layer via the LedgerService abstraction.
This is read-only for security - ledger entries are only created through services.
"""


from app.core.security import get_current_active_user
from app.modules.ledger.service.base import LedgerService
from app.modules.ledger.service.dependency import get_ledger_service
from app.schemas.ledger import (
    LedgerBalanceResponse,
    LedgerEntryResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_ledger_service_depends = Depends(get_ledger_service)


@router.get("/entries", response_model=list[LedgerEntryResponse])
async def list_ledger_entries(
    current_user: dict = get_current_active_user_depends,
    service: LedgerService = get_ledger_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    merchant_id: str | None = None,
    entry_type: str | None = None,
    account_type: str | None = None,
    direction: str | None = None,
    min_amount: int | None = None,
    max_amount: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    List ledger entries with filtering.
    Access restrictions:
    - Buyers: Can only see ledger entries related to their orders
    - Merchants: Can only see ledger entries related to their merchant wallet
    - Platform admins: Can see all ledger entries
    """
    return await service.list_entries(
        skip=skip,
        limit=limit,
        merchant_id=merchant_id,
        entry_type=entry_type,
        account_type=account_type,
        direction=direction,
        min_amount=min_amount,
        max_amount=max_amount,
        user_id=str(current_user.id),
        user_role=current_user.role.value,
    )


@router.get("/entries/{entry_id}", response_model=LedgerEntryResponse)
async def get_ledger_entry(
    entry_id: str,
    current_user: dict = get_current_active_user_depends,
    service: LedgerService = get_ledger_service_depends,
):
    """Get a ledger entry by ID."""
    entry = await service.get_entry(entry_id)

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ledger entry not found",
        )

    return entry


@router.get("/balance/{merchant_id}", response_model=LedgerBalanceResponse)
async def get_merchant_balance(
    merchant_id: str,
    current_user: dict = get_current_active_user_depends,
    service: LedgerService = get_ledger_service_depends,
):
    """
    Get the balance for a merchant.
    Access restrictions:
    - Merchants: Can only check their own balance
    - Platform admins: Can check any merchant's balance
    - Buyers: Cannot check merchant balances
    """
    try:
        return await service.get_balance(
            merchant_id=merchant_id,
            user_id=str(current_user.id),
            user_role=current_user.role.value,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(e)
        )


# Include the router in the main app
def get_router():
    return router
