# app/modules/commissions/service/base.py
"""
Abstract base class for commission service.
Defines the interface that all commission service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.commission_plans import CommissionPlanCreate, CommissionPlanResponse


class CommissionService(ABC):
    """
    Abstract interface for commission plan operations.
    
    This class defines the contract for any commission service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def create_commission_plan(self, plan_data: CommissionPlanCreate) -> CommissionPlanResponse:
        """
        Create a new commission plan.
        
        Args:
            plan_data: The commission plan data to create.
            
        Returns:
            The created commission plan response.
        """
        ...

    @abstractmethod
    async def list_commission_plans(self, skip: int = 0, limit: int = 100) -> list[CommissionPlanResponse]:
        """
        List commission plans with pagination.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of commission plan responses.
        """
        ...

    @abstractmethod
    async def get_commission_plan(self, plan_id: str) -> CommissionPlanResponse | None:
        """
        Get a commission plan by ID.
        
        Args:
            plan_id: The commission plan ID.
            
        Returns:
            The commission plan response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_default_commission_plan(self) -> CommissionPlanResponse | None:
        """
        Get the default commission plan.
        
        Returns:
            The default commission plan response if found, None otherwise.
        """
        ...
