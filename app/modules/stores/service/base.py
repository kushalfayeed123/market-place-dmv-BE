# app/modules/stores/service/base.py
"""
Abstract base class for store service.
Defines the interface that all store service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.store import StoreCreate, StoreResponse


class StoreService(ABC):
    """
    Abstract interface for store operations.
    
    This class defines the contract for any store service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def create_store(self, store_data: StoreCreate) -> StoreResponse:
        """
        Create a new store.
        
        Args:
            store_data: The store data to create.
            
        Returns:
            The created store response.
            
        Raises:
            ValueError: If store data is invalid.
        """
        ...

    @abstractmethod
    async def list_stores(
        self, 
        skip: int = 0, 
        limit: int = 100,
        merchant_id: str | None = None
    ) -> list[StoreResponse]:
        """
        List stores with pagination.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            merchant_id: Filter by merchant ID.
            
        Returns:
            List of store responses.
        """
        ...

    @abstractmethod
    async def get_store(self, store_id: str) -> StoreResponse | None:
        """
        Get a store by ID.
        
        Args:
            store_id: The unique identifier of the store.
            
        Returns:
            The store response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_stores_by_merchant(self, merchant_id: str) -> list[StoreResponse]:
        """
        List all stores for a specific merchant.
        
        Args:
            merchant_id: The merchant ID.
            
        Returns:
            List of store responses.
        """
        ...
