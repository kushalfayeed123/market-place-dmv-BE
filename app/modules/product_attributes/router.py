# app/modules/product_attributes/router.py
"""
Product attribute schemas router.
Handles CRUD operations for product attribute schemas.
"""

from app.core.security import get_current_active_user
from app.modules.product_attributes.service.base import ProductAttributeSchemaService
from app.modules.product_attributes.service.dependency import (
    get_product_attribute_schema_service,
)
from app.schemas.product_attribute_schema import (
    ProductAttributeSchemaCreate,
    ProductAttributeSchemaResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, status

router = APIRouter()

# Module-level dependency singletons
get_current_active_user_depends = Depends(get_current_active_user)
get_product_attribute_schema_service_depends = Depends(get_product_attribute_schema_service)


@router.post("/", response_model=ProductAttributeSchemaResponse)
async def create_schema(
    schema_data: ProductAttributeSchemaCreate,
    current_user: dict = get_current_active_user_depends,
    service: ProductAttributeSchemaService = get_product_attribute_schema_service_depends,
):
    """Create a new product attribute schema for a category."""
    # Check permissions
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        return await service.create_schema(schema_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/", response_model=list[ProductAttributeSchemaResponse])
async def list_schemas(
    current_user: dict = get_current_active_user_depends,
    service: ProductAttributeSchemaService = get_product_attribute_schema_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List all product attribute schemas."""
    return await service.list_schemas(skip=skip, limit=limit)


@router.get("/{category_id}", response_model=ProductAttributeSchemaResponse)
async def get_schema(
    category_id: str,
    current_user: dict = get_current_active_user_depends,
    service: ProductAttributeSchemaService = get_product_attribute_schema_service_depends,
):
    """Get a product attribute schema by category ID."""
    schema = await service.get_schema(category_id)

    if not schema:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attribute schema not found for this category",
        )

    return schema


@router.put("/{category_id}", response_model=ProductAttributeSchemaResponse)
async def update_schema(
    category_id: str,
    schema_data: ProductAttributeSchemaCreate,
    current_user: dict = get_current_active_user_depends,
    service: ProductAttributeSchemaService = get_product_attribute_schema_service_depends,
):
    """Update a product attribute schema for a category."""
    # Check permissions
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        return await service.update_schema(category_id, schema_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete("/{category_id}")
async def delete_schema(
    category_id: str,
    current_user: dict = get_current_active_user_depends,
    service: ProductAttributeSchemaService = get_product_attribute_schema_service_depends,
):
    """Delete a product attribute schema."""
    # Check permissions
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    deleted = await service.delete_schema(category_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Attribute schema not found for this category",
        )

    return {"message": "Attribute schema deleted successfully"}


# Include the router in the main app
def get_router():
    return router
