# app/modules/product_attributes/service/base.py
"""
Abstract base class for product attribute schema service.
Defines the interface that all implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.product_attribute_schema import ProductAttributeSchemaCreate, ProductAttributeSchemaResponse


class ProductAttributeSchemaService(ABC):
    """
    Abstract interface for product attribute schema operations.
    """

    @abstractmethod
    async def create_schema(self, schema_data: ProductAttributeSchemaCreate) -> ProductAttributeSchemaResponse:
        """
        Create a new product attribute schema for a category.
        
        Args:
            schema_data: The schema data to create.
            
        Returns:
            The created schema response.
            
        Raises:
            ValueError: If category doesn't exist or schema already exists.
        """
        ...

    @abstractmethod
    async def get_schema(self, category_id: str) -> ProductAttributeSchemaResponse | None:
        """
        Get a product attribute schema by category ID.
        
        Args:
            category_id: The category ID.
            
        Returns:
            The schema response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_schemas(self, skip: int = 0, limit: int = 100) -> list[ProductAttributeSchemaResponse]:
        """
        List all product attribute schemas.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of schema responses.
        """
        ...

    @abstractmethod
    async def update_schema(
        self, category_id: str, schema_data: ProductAttributeSchemaCreate
    ) -> ProductAttributeSchemaResponse:
        """
        Update a product attribute schema for a category.
        
        Args:
            category_id: The category ID.
            schema_data: The updated schema data.
            
        Returns:
            The updated schema response.
            
        Raises:
            ValueError: If schema doesn't exist.
        """
        ...

    @abstractmethod
    async def delete_schema(self, category_id: str) -> bool:
        """
        Delete a product attribute schema.
        
        Args:
            category_id: The category ID.
            
        Returns:
            True if deleted, False if not found.
        """
        ...
