# app/modules/product_attributes/service/implementation.py
"""
Concrete implementation of the product attribute schema service.
Handles database operations using SQLAlchemy.
"""

import json

from app.core.security import to_uuid
from app.models.category import Category
from app.models.product_attribute_schema import ProductAttributeSchema
from app.modules.product_attributes.service.base import ProductAttributeSchemaService
from app.schemas.product_attribute_schema import (
    ProductAttributeSchemaCreate,
    ProductAttributeSchemaResponse,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class ProductAttributeSchemaServiceImpl(ProductAttributeSchemaService):
    """
    Database-backed implementation of ProductAttributeSchemaService.
    """

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_schema(self, schema_data: ProductAttributeSchemaCreate) -> ProductAttributeSchemaResponse:
        """
        Create a new product attribute schema for a category.
        
        Raises:
            ValueError: If category doesn't exist or schema already exists.
        """
        try:
            category_uuid = to_uuid(schema_data.category_id)
        except ValueError:
            raise ValueError(f"Invalid category_id format: '{schema_data.category_id}'")

        # Verify category exists
        result = await self._db.execute(
            select(Category).where(Category.id == category_uuid)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"Category with id '{schema_data.category_id}' does not exist")

        # Check if schema already exists for this category
        result = await self._db.execute(
            select(ProductAttributeSchema).where(ProductAttributeSchema.category_id == category_uuid)
        )
        if result.scalar_one_or_none() is not None:
            raise ValueError(f"Attribute schema already exists for category '{schema_data.category_id}'")

        # Create new schema
        new_schema = ProductAttributeSchema(
            category_id=category_uuid,
            schema=json.dumps(schema_data.schema),
        )

        self._db.add(new_schema)
        await self._db.commit()
        await self._db.refresh(new_schema)

        return self._to_response(new_schema)

    async def get_schema(self, category_id: str) -> ProductAttributeSchemaResponse | None:
        """
        Get a product attribute schema by category ID.
        """
        try:
            category_uuid = to_uuid(category_id)
        except ValueError:
            return None

        result = await self._db.execute(
            select(ProductAttributeSchema).where(ProductAttributeSchema.category_id == category_uuid)
        )
        schema = result.scalar_one_or_none()

        if schema is None:
            return None

        return self._to_response(schema)

    async def list_schemas(self, skip: int = 0, limit: int = 100) -> list[ProductAttributeSchemaResponse]:
        """
        List all product attribute schemas.
        """
        result = await self._db.execute(
            select(ProductAttributeSchema).offset(skip).limit(limit)
        )
        schemas = result.scalars().all()

        return [self._to_response(schema) for schema in schemas]

    async def update_schema(
        self, category_id: str, schema_data: ProductAttributeSchemaCreate
    ) -> ProductAttributeSchemaResponse:
        """
        Update a product attribute schema for a category.
        
        Raises:
            ValueError: If schema doesn't exist.
        """
        try:
            category_uuid = to_uuid(category_id)
        except ValueError:
            raise ValueError(f"Invalid category_id format: '{category_id}'")

        # Verify category exists
        result = await self._db.execute(
            select(Category).where(Category.id == category_uuid)
        )
        if result.scalar_one_or_none() is None:
            raise ValueError(f"Category with id '{category_id}' does not exist")

        # Find existing schema
        result = await self._db.execute(
            select(ProductAttributeSchema).where(ProductAttributeSchema.category_id == category_uuid)
        )
        existing_schema = result.scalar_one_or_none()

        if existing_schema is None:
            raise ValueError(f"No attribute schema found for category '{category_id}'")

        # Update schema
        existing_schema.schema = json.dumps(schema_data.schema)
        await self._db.commit()
        await self._db.refresh(existing_schema)

        return self._to_response(existing_schema)

    async def delete_schema(self, category_id: str) -> bool:
        """
        Delete a product attribute schema.
        """
        try:
            category_uuid = to_uuid(category_id)
        except ValueError:
            return False

        result = await self._db.execute(
            select(ProductAttributeSchema).where(ProductAttributeSchema.category_id == category_uuid)
        )
        schema = result.scalar_one_or_none()

        if schema is None:
            return False

        await self._db.delete(schema)
        await self._db.commit()

        return True

    @staticmethod
    def _to_response(schema: ProductAttributeSchema) -> ProductAttributeSchemaResponse:
        """
        Convert a ProductAttributeSchema model to a response schema.
        """
        # Parse schema from JSON string to dict if needed
        schema_data = schema.schema
        if isinstance(schema_data, str):
            try:
                schema_data = json.loads(schema_data)
            except (json.JSONDecodeError, TypeError):
                schema_data = {}

        return ProductAttributeSchemaResponse(
            category_id=str(schema.category_id),
            schema=schema_data or {},
        )
