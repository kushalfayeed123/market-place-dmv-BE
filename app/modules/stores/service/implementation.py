# app/modules/stores/service/implementation.py
"""
Concrete implementation of the store service.
Handles database operations for stores using SQLAlchemy.
"""

import json

from app.core.security import to_uuid
from app.models.store import Store
from app.modules.stores.service.base import StoreService
from app.schemas.store import StoreCreate, StoreResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class StoreServiceImpl(StoreService):
    """
    Database-backed implementation of StoreService.
    
    This class encapsulates all database operations for stores,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def create_store(self, store_data: StoreCreate) -> StoreResponse:
        """
        Create a new store in the database.
        
        Args:
            store_data: The store data to create.
            
        Returns:
            The created store response.
            
        Raises:
            ValueError: If merchant_id is invalid.
        """
        try:
            merchant_uuid = to_uuid(store_data.merchant_id)
        except ValueError:
            raise ValueError(f"Invalid merchant_id format: '{store_data.merchant_id}'")

        new_store = Store(
            merchant_id=merchant_uuid,
            name=store_data.name,
            slug=store_data.slug,
            branding=json.dumps(store_data.branding or {}),
        )

        self._db.add(new_store)
        await self._db.commit()
        await self._db.refresh(new_store)

        return self._to_response(new_store)

    async def list_stores(
        self, 
        skip: int = 0, 
        limit: int = 100,
        merchant_id: str | None = None
    ) -> list[StoreResponse]:
        """
        List stores with pagination from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            merchant_id: Filter by merchant ID.
            
        Returns:
            List of store responses.
        """
        query = select(Store)
        
        if merchant_id:
            try:
                merchant_uuid = to_uuid(merchant_id)
                query = query.where(Store.merchant_id == merchant_uuid)
            except ValueError:
                return []  # Invalid UUID returns empty list
        
        query = query.offset(skip).limit(limit)
        result = await self._db.execute(query)
        stores = result.scalars().all()

        return [self._to_response(store) for store in stores]

    async def get_store(self, store_id: str) -> StoreResponse | None:
        """
        Get a store by ID from the database.
        
        Args:
            store_id: The unique identifier of the store.
            
        Returns:
            The store response if found, None otherwise.
        """
        try:
            store_uuid = to_uuid(store_id)
        except ValueError:
            return None

        result = await self._db.execute(
            select(Store).where(Store.id == store_uuid)
        )
        store = result.scalar_one_or_none()

        if store is None:
            return None

        return self._to_response(store)

    async def list_stores_by_merchant(self, merchant_id: str) -> list[StoreResponse]:
        """
        List all stores for a specific merchant.
        
        Args:
            merchant_id: The merchant ID.
            
        Returns:
            List of store responses.
        """
        try:
            merchant_uuid = to_uuid(merchant_id)
        except ValueError:
            return []

        result = await self._db.execute(
            select(Store).where(Store.merchant_id == merchant_uuid)
        )
        stores = result.scalars().all()

        return [self._to_response(store) for store in stores]

    @staticmethod
    def _to_response(store: Store) -> StoreResponse:
        """
        Convert a Store model instance to a StoreResponse schema.
        
        Args:
            store: The SQLAlchemy Store model instance.
            
        Returns:
            The store response schema.
        """
        import json
        
        # Parse branding from JSON string to dict if needed
        branding = store.branding
        if isinstance(branding, str):
            try:
                branding = json.loads(branding)
            except (json.JSONDecodeError, TypeError):
                branding = {}
        
        return StoreResponse(
            id=str(store.id),
            merchant_id=str(store.merchant_id),
            name=store.name,
            slug=store.slug,
            branding=branding or {},
            created_at=store.created_at,
            updated_at=store.updated_at,
        )
