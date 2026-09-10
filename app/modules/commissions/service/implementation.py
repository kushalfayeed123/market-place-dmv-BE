# app/modules/commissions/service/implementation.py
"""
Concrete implementation of the commission service.
Handles database operations for commission plans using SQLAlchemy.
"""

from app.core.security import to_uuid
from app.models.commission_plan import CommissionPlan
from app.modules.commissions.service.base import CommissionService
from app.schemas.commission_plans import CommissionPlanCreate, CommissionPlanResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CommissionServiceImpl(CommissionService):
    """
    Database-backed implementation of CommissionService.
    
    This class encapsulates all database operations for commission plans,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def create_commission_plan(self, plan_data: CommissionPlanCreate) -> CommissionPlanResponse:
        """
        Create a new commission plan in the database.
        
        Args:
            plan_data: The commission plan data to create.
            
        Returns:
            The created commission plan response.
        """
        new_plan = CommissionPlan(
            name=plan_data.name,
            percentage_bps=plan_data.percentage_bps,
            flat_fee_minor=plan_data.flat_fee_minor,
            currency=plan_data.currency,
            is_default=plan_data.is_default,
        )

        self._db.add(new_plan)
        await self._db.commit()
        await self._db.refresh(new_plan)

        return self._to_response(new_plan)

    async def list_commission_plans(self, skip: int = 0, limit: int = 100) -> list[CommissionPlanResponse]:
        """
        List commission plans with pagination from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of commission plan responses.
        """
        result = await self._db.execute(
            select(CommissionPlan).offset(skip).limit(limit)
        )
        plans = result.scalars().all()

        return [self._to_response(plan) for plan in plans]

    async def get_commission_plan(self, plan_id: str) -> CommissionPlanResponse | None:
        """
        Get a commission plan by ID from the database.
        
        Args:
            plan_id: The commission plan ID.
            
        Returns:
            The commission plan response if found, None otherwise.
        """
        try:
            plan_uuid = to_uuid(plan_id)
        except ValueError:
            return None
        
        result = await self._db.execute(
            select(CommissionPlan).where(CommissionPlan.id == plan_uuid)
        )
        plan = result.scalar_one_or_none()

        if plan is None:
            return None

        return self._to_response(plan)

    async def get_default_commission_plan(self) -> CommissionPlanResponse | None:
        """
        Get the default commission plan from the database.
        
        Returns:
            The default commission plan response if found, None otherwise.
        """
        result = await self._db.execute(
            select(CommissionPlan).where(CommissionPlan.is_default == True)
        )
        plan = result.scalar_one_or_none()

        if plan is None:
            return None

        return self._to_response(plan)

    @staticmethod
    def _to_response(plan: CommissionPlan) -> CommissionPlanResponse:
        """Convert a CommissionPlan model to CommissionPlanResponse schema."""
        return CommissionPlanResponse(
            id=str(plan.id),
            name=plan.name,
            percentage_bps=plan.percentage_bps,
            flat_fee_minor=plan.flat_fee_minor,
            currency=plan.currency,
            is_default=plan.is_default,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
        )
