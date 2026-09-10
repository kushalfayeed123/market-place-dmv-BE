# app/modules/catalog/service/implementation.py
"""
Concrete implementation of the catalog service.
Handles database operations for catalog using SQLAlchemy.
"""


import json

from app.core.security import to_uuid
from app.models.category import Category
from app.models.inventory import Inventory
from app.models.product import Product, ProductStatus
from app.models.product_attribute_schema import ProductAttributeSchema
from app.models.product_variant import ProductVariant
from app.modules.catalog.service.base import CatalogService
from app.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    InventoryUpdate,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class CatalogServiceImpl(CatalogService):
    """
    Database-backed implementation of CatalogService.
    
    This class encapsulates all database operations for catalog,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def create_category(self, category_data: CategoryCreate) -> CategoryResponse:
        """
        Create a new category in the database.

        Args:
            category_data: The category data to create.

        Returns:
            The created category response.

        Raises:
            ValueError: If parent_id is provided but does not exist, or is invalid UUID.
        """
        parent_uuid = None
        if category_data.parent_id:
            try:
                parent_uuid = to_uuid(category_data.parent_id)
            except ValueError:
                raise ValueError(f"Invalid parent_id format: '{category_data.parent_id}'")
            # Validate that parent category exists
            result = await self._db.execute(
                select(Category).where(Category.id == parent_uuid)
            )
            if result.scalar_one_or_none() is None:
                raise ValueError(f"Parent category with id '{category_data.parent_id}' does not exist")

        new_category = Category(
            name=category_data.name,
            parent_id=parent_uuid,
        )

        self._db.add(new_category)
        await self._db.commit()
        await self._db.refresh(new_category)

        return self._category_to_response(new_category)

    async def get_category(self, category_id: str) -> CategoryResponse | None:
        """
        Get a category by ID from the database.

        Args:
            category_id: The category ID.

        Returns:
            The category response if found, None otherwise.
        """
        try:
            category_uuid = to_uuid(category_id)
        except ValueError:
            return None

        result = await self._db.execute(
            select(Category).where(Category.id == category_uuid)
        )
        category = result.scalar_one_or_none()

        if category is None:
            return None

        return self._category_to_response(category)

    async def list_categories(self, skip: int = 0, limit: int = 100) -> list[CategoryResponse]:
        """
        List categories with pagination from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of category responses.
        """
        result = await self._db.execute(
            select(Category).offset(skip).limit(limit)
        )
        categories = result.scalars().all()

        return [self._category_to_response(category) for category in categories]

    async def create_product(self, product_data: ProductCreate) -> ProductResponse:
        """
        Create a new product in the database.
        
        Args:
            product_data: The product data to create.
            
        Returns:
            The created product response.
            
        Raises:
            ValueError: If category_id is missing, category doesn't exist, or attributes don't match schema.
        """
        import json
        
        # Validate category_id is provided
        if not product_data.category_id:
            raise ValueError("category_id is required to create a product")
        
        try:
            category_uuid = to_uuid(product_data.category_id)
        except ValueError:
            raise ValueError(f"Invalid category_id format: '{product_data.category_id}'")
        
        # Verify category exists
        result = await self._db.execute(
            select(Category).where(Category.id == category_uuid)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"Category with id '{product_data.category_id}' does not exist")
        
        # Check if category has an attribute schema and validate
        result = await self._db.execute(
            select(ProductAttributeSchema).where(ProductAttributeSchema.category_id == category_uuid)
        )
        attribute_schema = result.scalar_one_or_none()
        
        if attribute_schema:
            # Parse the schema from JSON string
            try:
                schema = json.loads(attribute_schema.schema) if isinstance(attribute_schema.schema, str) else attribute_schema.schema
            except (json.JSONDecodeError, TypeError):
                schema = {}
            
            # Validate attributes against schema
            attributes = product_data.attributes or {}
            self._validate_attributes(attributes, schema)
        
        new_product = Product(
            merchant_id=to_uuid(product_data.merchant_id),
            store_id=to_uuid(product_data.store_id),
            category_id=category_uuid,
            title=product_data.title,
            slug=product_data.slug,
            description=product_data.description,
            fulfillment_type=product_data.fulfillment_type,
            status=product_data.status or ProductStatus.DRAFT,
            base_price_amount=product_data.base_price_amount,
            base_price_currency=product_data.base_price_currency,
            attributes=json.dumps(product_data.attributes or {}),
        )

        self._db.add(new_product)
        await self._db.commit()
        await self._db.refresh(new_product)

        return self._product_to_response(new_product)

    @staticmethod
    def _validate_attributes(attributes: dict, schema: dict) -> None:
        """
        Validate product attributes against a JSON schema.
        
        Args:
            attributes: The product attributes to validate.
            schema: The JSON schema to validate against.
            
        Raises:
            ValueError: If attributes don't match the schema.
        """
        if not schema:
            return
        
        # Check required fields
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in attributes:
                raise ValueError(f"Missing required attribute: '{field}'")
        
        # Check property types
        properties = schema.get("properties", {})
        for field, value in attributes.items():
            if field in properties:
                field_schema = properties[field]
                expected_type = field_schema.get("type")
                
                # Type validation
                if expected_type == "string" and not isinstance(value, str):
                    raise ValueError(f"Attribute '{field}' must be a string")
                elif expected_type == "number" and not isinstance(value, (int, float)):
                    raise ValueError(f"Attribute '{field}' must be a number")
                elif expected_type == "integer" and not isinstance(value, int):
                    raise ValueError(f"Attribute '{field}' must be an integer")
                elif expected_type == "boolean" and not isinstance(value, bool):
                    raise ValueError(f"Attribute '{field}' must be a boolean")
                
                # Enum validation
                enum_values = field_schema.get("enum")
                if enum_values and value not in enum_values:
                    raise ValueError(f"Attribute '{field}' must be one of: {enum_values}")

    async def get_product(self, product_id: str) -> ProductResponse | None:
        """
        Get a product by ID from the database.
        
        Args:
            product_id: The product ID.
            
        Returns:
            The product response if found, None otherwise.
        """
        try:
            product_uuid = to_uuid(product_id)
        except ValueError:
            return None

        result = await self._db.execute(
            select(Product).where(Product.id == product_uuid)
        )
        product = result.scalar_one_or_none()

        if product is None:
            return None

        # Fetch variants for this product
        variants_result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product_uuid)
        )
        variants = variants_result.scalars().all()

        # Fetch inventory quantities for these variants
        inventory_quantities = self._inventory_quantities_map(variants)

        return self._product_to_response(product, variants, inventory_quantities)

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
        List products with optional filtering from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            merchant_id: Filter by merchant ID.
            category_id: Filter by category ID.
            status: Filter by product status.
            
        Returns:
            List of product responses.
        """
        query = select(Product)

        if merchant_id:
            try:
                query = query.where(Product.merchant_id == to_uuid(merchant_id))
            except ValueError:
                return []  # Invalid UUID returns empty list
        if category_id:
            try:
                query = query.where(Product.category_id == to_uuid(category_id))
            except ValueError:
                return []  # Invalid UUID returns empty list
        if status:
            query = query.where(Product.status == status)

        # Free-text search: match against title, slug, or description
        if search_query:
            from sqlalchemy import or_
            search_pattern = f"%{search_query}%"
            query = query.where(
                or_(
                    Product.title.ilike(search_pattern),
                    Product.slug.ilike(search_pattern),
                    Product.description.ilike(search_pattern),
                )
            )

        # Price range filter (on base_price_amount)
        if price_min is not None:
            query = query.where(Product.base_price_amount >= price_min)
        if price_max is not None:
            query = query.where(Product.base_price_amount <= price_max)

        # Currency filter
        if currency:
            query = query.where(Product.base_price_currency == currency.upper())

        query = query.offset(skip).limit(limit)
        result = await self._db.execute(query)
        products = result.scalars().all()
        
        # Fetch all variants for these products in a single query
        product_uuids = [p.id for p in products]
        variants_result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.product_id.in_(product_uuids))
        )
        variants_by_product = {}
        all_variants = []
        for variant in variants_result.scalars().all():
            product_id = variant.product_id
            if product_id not in variants_by_product:
                variants_by_product[product_id] = []
            variants_by_product[product_id].append(variant)
            all_variants.append(variant)

        # Fetch inventory quantities for all variants
        inventory_quantities = self._inventory_quantities_map(all_variants)

        return [
            self._product_to_response(product, variants_by_product.get(product.id, []), inventory_quantities)
            for product in products
        ]

    async def create_product_variant(
        self, product_id: str, variant_data: ProductVariantCreate
    ) -> ProductVariantResponse:
        """
        Create a new product variant in the database.
        
        Args:
            product_id: The parent product ID.
            variant_data: The variant data to create.
            
        Returns:
            The created variant response.
            
        Raises:
            ValueError: If product not found or invalid UUID.
        """
        # Convert and validate UUID
        try:
            product_uuid = to_uuid(product_id)
        except ValueError:
            raise ValueError("Invalid product ID format")

        # Verify product exists
        result = await self._db.execute(
            select(Product).where(Product.id == product_uuid)
        )
        product = result.scalar_one_or_none()

        if not product:
            raise ValueError("Product not found")

        new_variant = ProductVariant(
            product_id=product_uuid,
            sku=variant_data.sku,
            attributes=json.dumps(variant_data.attributes or {}),
            price_override_amount=variant_data.price_override_amount,
            price_override_currency=variant_data.price_override_currency,
            inventory_policy=variant_data.inventory_policy or "tracked",
        )

        self._db.add(new_variant)
        await self._db.commit()
        await self._db.refresh(new_variant)

                # Create initial inventory record with provided values or defaults
        inventory = Inventory(
            variant_id=new_variant.id,
            quantity_available=variant_data.quantity_available or 0,
            quantity_reserved=variant_data.quantity_reserved or 0,
        )
        self._db.add(inventory)
        await self._db.commit()


        return self._variant_to_response(new_variant)

    async def update_inventory(
        self, variant_id: str, inventory_data: InventoryUpdate
    ) -> dict:
        """
        Update inventory for a product variant in the database.
        
        Args:
            variant_id: The variant ID.
            inventory_data: The inventory update data.
            
        Returns:
            Dictionary with updated inventory details.
            
        Raises:
            ValueError: If variant not found or invalid UUID.
        """
        # Convert and validate UUID
        try:
            variant_uuid = to_uuid(variant_id)
        except ValueError:
            raise ValueError("Invalid variant ID format")

        # Verify variant exists
        result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.id == variant_uuid)
        )
        variant = result.scalar_one_or_none()

        if not variant:
            raise ValueError("Product variant not found")

        # Get or create inventory record
        result = await self._db.execute(
            select(Inventory).where(Inventory.variant_id == variant_uuid)
        )
        inventory = result.scalar_one_or_none()

        if not inventory:
            inventory = Inventory(
                variant_id=variant_uuid,
                quantity_available=inventory_data.quantity_available or 0,
                quantity_reserved=inventory_data.quantity_reserved or 0,
            )
            self._db.add(inventory)
        else:
            if inventory_data.quantity_available is not None:
                inventory.quantity_available = inventory_data.quantity_available
            if inventory_data.quantity_reserved is not None:
                inventory.quantity_reserved = inventory_data.quantity_reserved

        await self._db.commit()
        await self._db.refresh(inventory)

        return {
            "id": str(inventory.id),
            "variant_id": str(inventory.variant_id),
            "quantity_available": inventory.quantity_available,
            "quantity_reserved": inventory.quantity_reserved,
            "updated_at": inventory.updated_at.isoformat(),
        }

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
        try:
            product_uuid = to_uuid(product_id)
        except ValueError:
            raise ValueError("Invalid product ID format")

        # Verify product exists
        result = await self._db.execute(
            select(Product).where(Product.id == product_uuid)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Product not found")

        # Fetch all variants for this product
        variants_result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product_uuid)
        )
        variants = variants_result.scalars().all()

        return [self._variant_to_response(variant) for variant in variants]

    async def get_variant_by_sku(self, sku: str) -> ProductVariantResponse | None:
        """
        Get a product variant by SKU.
        
        Args:
            sku: The variant SKU.
            
        Returns:
            The variant response if found, None otherwise.
        """
        result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.sku == sku)
        )
        variant = result.scalar_one_or_none()
        return self._variant_to_response(variant) if variant else None

    async def get_product_by_variant_sku(self, sku: str) -> ProductResponse | None:
        """
        Get a product by its variant SKU.
        
        Args:
            sku: The variant SKU to search by.
            
        Returns:
            The product response (with variants) if found, None otherwise.
        """
        # First find the variant by SKU
        variant_result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.sku == sku)
        )
        variant = variant_result.scalar_one_or_none()
        if variant is None:
            return None

        # Then fetch the product and all its variants
        product_result = await self._db.execute(
            select(Product).where(Product.id == variant.product_id)
        )
        product = product_result.scalar_one_or_none()
        if product is None:
            return None

        variants_result = await self._db.execute(
            select(ProductVariant).where(ProductVariant.product_id == product.id)
        )
        variants = variants_result.scalars().all()

        return self._product_to_response(product, variants)

    @staticmethod
    def _category_to_response(category: Category) -> CategoryResponse:
        """Convert a Category model to CategoryResponse schema."""
        return CategoryResponse(
            id=str(category.id),
            name=category.name,
            parent_id=str(category.parent_id) if category.parent_id else None,
            created_at=category.created_at,
            updated_at=category.updated_at,
        )

    @staticmethod
    def _product_to_response(
        product: Product,
        variants: list | None = None,
        inventory_quantities: dict | None = None,
    ) -> ProductResponse:
        """Convert a Product model to ProductResponse schema.

        Args:
            product: The Product model instance.
            variants: List of ProductVariant model instances. If None, fetches
                nothing.
            inventory_quantities: Optional dict mapping variant_id (UUID) to
                quantity_available (int). When provided, each variant's
                quantity_available is populated from this dict. When absent,
                variant quantity_available defaults to None.
        """
        import json

        # Parse attributes from JSON string to dict if needed
        attributes = product.attributes
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except (json.JSONDecodeError, TypeError):
                attributes = {}

        # Parse variant attributes and convert
        variant_responses = []
        for variant in (variants or []):
            variant_qty = None
            if inventory_quantities:
                variant_qty = inventory_quantities.get(variant.id)
            variant_responses.append(
                CatalogServiceImpl._variant_to_response(
                    variant, quantity_available=variant_qty
                )
            )

        return ProductResponse(
            id=str(product.id),
            merchant_id=str(product.merchant_id),
            store_id=str(product.store_id),
            category_id=str(product.category_id) if product.category_id else None,
            title=product.title,
            slug=product.slug,
            description=product.description,
            fulfillment_type=product.fulfillment_type,
            status=product.status,
            base_price_amount=product.base_price_amount,
            base_price_currency=product.base_price_currency,
            attributes=attributes or {},
            created_at=product.created_at,
            updated_at=product.updated_at,
            variants=variant_responses,
        )

    @staticmethod
    def _inventory_quantities_map(variants: list) -> dict:
        """Build a {variant_id: quantity_available} map for a list of variants.

        Fetches Inventory rows in bulk and joins them to variants. Variants
        with no Inventory row default to 0.
        """
        if not variants:
            return {}
        from app.models.inventory import Inventory
        from sqlalchemy import select
        variant_ids = [v.id for v in variants]
        result = CatalogServiceImpl._db.execute(
            select(Inventory).where(Inventory.variant_id.in_(variant_ids))
        )
        by_variant = {row.variant_id: row.quantity_available for row in result.scalars()}
        return {v.id: by_variant.get(v.id, 0) for v in variants}

    @staticmethod
    def _variant_to_response(variant: ProductVariant, quantity_available: int | None = None) -> ProductVariantResponse:
        """Convert a ProductVariant model to ProductVariantResponse schema."""
        import json
        
        # Parse attributes from JSON string to dict if needed
        attributes = variant.attributes
        if isinstance(attributes, str):
            try:
                attributes = json.loads(attributes)
            except (json.JSONDecodeError, TypeError):
                attributes = {}
        
        return ProductVariantResponse(
            id=str(variant.id),
            product_id=str(variant.product_id),
            sku=variant.sku,
            attributes=attributes or {},
            price_override_amount=variant.price_override_amount,
            price_override_currency=variant.price_override_currency,
            inventory_policy=variant.inventory_policy,
            quantity_available=quantity_available,
            created_at=variant.created_at,
            updated_at=variant.updated_at,
        )
