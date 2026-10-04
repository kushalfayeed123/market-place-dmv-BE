# app/modules/catalog/service/base.py
"""
Abstract base class for catalog service.
Defines the interface that all catalog service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    InventoryUpdate,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
)


class CatalogService(ABC):
    """
    Abstract interface for catalog operations.
    
    This class defines the contract for any catalog service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def create_category(self, category_data: CategoryCreate) -> CategoryResponse:
        """
        Create a new product category.
        
        Args:
            category_data: The category data to create.
            
        Returns:
            The created category response.
        """
        ...

    @abstractmethod
    async def list_categories(self, skip: int = 0, limit: int = 100) -> list[CategoryResponse]:
        """
        List product categories with pagination.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of category responses.
        """
        ...

    @abstractmethod
    async def get_category(self, category_id: str) -> CategoryResponse | None:
        """
        Get a category by ID.
        
        Args:
            category_id: The category ID.
            
        Returns:
            The category response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def create_product(self, product_data: ProductCreate) -> ProductResponse:
        """
        Create a new product.
        
        Args:
            product_data: The product data to create.
            
                Returns:
            The created product response.
        """
        ...

    @abstractmethod
    async def add_product_image(self, product_id: str, image_url: str) -> ProductResponse:
        """
        Append an image URL to a product's `urls`.

        Args:
            product_id: The product ID.
            image_url: The image URL to associate with the product.

        Returns:
            The updated product response.

        Raises:
            ValueError: If the product does not exist.
        """
        ...

    @abstractmethod
    async def get_product(self, product_id: str) -> ProductResponse | None:
        """
        Get a product by ID.
        
        Args:
            product_id: The product ID.
            
        Returns:
            The product response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def list_products(
        self,
        skip: int = 0,
        limit: int = 100,
        merchant_id: str | None = None,
        category_id: str | None = None,
        status: str | None = None,
        search_query: str | None = None,
        price_min: int | None = None,
        price_max: int | None = None,
        currency: str | None = None,
    ) -> list[ProductResponse]:
        """
        List products with optional filtering and free-text search.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            merchant_id: Filter by merchant ID.
            category_id: Filter by category ID.
            status: Filter by product status.
            search_query: Free-text search query (matches title, slug, description).
            price_min: Minimum price filter (inclusive, in minor units).
            price_max: Maximum price filter (inclusive, in minor units).
            currency: Currency code filter (ISO 4217).
            
        Returns:
            List of product responses.
        """
        ...

    @abstractmethod
    async def create_product_variant(
        self, product_id: str, variant_data: ProductVariantCreate
    ) -> ProductVariantResponse:
        """
        Create a new product variant.
        
        Args:
            product_id: The parent product ID.
            variant_data: The variant data to create.
            
        Returns:
            The created variant response.
            
        Raises:
            ValueError: If product not found.
        """
        ...

    @abstractmethod
    async def list_product_variants(self, product_id: str) -> list[ProductVariantResponse]:
        """
        List all variants for a product.
        
        Args:
            product_id: The product ID.
            
        Returns:
            List of variant responses.
            
        Raises:
            ValueError: If product not found.
        """
        ...

    @abstractmethod
    async def get_variant_by_sku(self, sku: str) -> ProductVariantResponse | None:
        """
        Get a product variant by SKU.
        
        Args:
            sku: The variant SKU.
            
        Returns:
            The variant response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_product_by_variant_sku(self, sku: str) -> ProductResponse | None:
        """
        Get a product by its variant SKU.
        
        Args:
            sku: The variant SKU to search by.
            
        Returns:
            The product response (with variants) if found, None otherwise.
        """
        ...

    @abstractmethod
    async def update_inventory(
        self, variant_id: str, inventory_data: InventoryUpdate
    ) -> dict:
        """
        Update inventory for a product variant.
        
        Args:
            variant_id: The variant ID.
            inventory_data: The inventory update data.
            
        Returns:
            Dictionary with updated inventory details.
            
        Raises:
            ValueError: If variant not found.
        """
        ...
