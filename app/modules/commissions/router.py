# app/modules/commissions/router.py
"""
Commission plans router handling commission plan operations.
Communicates with the service layer via the CommissionService abstraction.
"""


from app.core.security import get_current_active_user
from app.modules.commissions.service.base import CommissionService
from app.modules.commissions.service.dependency import get_commission_service
from app.schemas.commission_plans import CommissionPlanCreate, CommissionPlanResponse
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_commission_service_depends = Depends(get_commission_service)


@router.post("/", response_model=CommissionPlanResponse)
async def create_commission_plan(
    plan_data: CommissionPlanCreate,
    current_user: dict = get_current_active_user_depends,
    service: CommissionService = get_commission_service_depends,
):
    """Create a new commission plan. Only platform admins can create commission plans."""
    # Only platform admins can create commission plans
    if current_user.role.value != "platform_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform admins can create commission plans"
        )

    return await service.create_commission_plan(plan_data)


@router.get("/", response_model=list[CommissionPlanResponse])
async def list_commission_plans(
    service: CommissionService = get_commission_service_depends,
    skip: int = 0,
    limit: int = 100
):
    """List all commission plans."""
    return await service.list_commission_plans(skip=skip, limit=limit)


@router.get("/default", response_model=CommissionPlanResponse)
async def get_default_commission_plan(
    service: CommissionService = get_commission_service_depends,
):
    """Get the default commission plan."""
    plan = await service.get_default_commission_plan()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No default commission plan found"
        )

    return plan


@router.get("/{plan_id}", response_model=CommissionPlanResponse)
async def get_commission_plan(
    plan_id: str,
    service: CommissionService = get_commission_service_depends,
):
    """Get a commission plan by ID."""
    plan = await service.get_commission_plan(plan_id)

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Commission plan not found"
        )

    return plan


# Include the router in the main app
def get_router():
    return router
