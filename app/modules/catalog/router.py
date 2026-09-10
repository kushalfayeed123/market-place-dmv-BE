# app/modules/catalog/router.py
"""
Catalog router handling products, categories, and inventory.
Communicates with the service layer via the CatalogService abstraction.
"""


from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.security import get_current_active_user
from app.modules.catalog.service.base import CatalogService
from app.modules.catalog.service.dependency import get_catalog_service
from app.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    InventoryUpdate,
    ProductCreate,
    ProductResponse,
    ProductVariantCreate,
    ProductVariantResponse,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_catalog_service_depends = Depends(get_catalog_service)


# Category endpoints
@router.post("/categories", response_model=CategoryResponse)
async def create_category(
    request: Request,
    category_data: CategoryCreate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Create a new product category."""
    # Check if user has permission (merchant owner or staff)
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.create_category(category_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(
    service: CatalogService = get_catalog_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """List product categories."""
    return await service.list_categories(skip=skip, limit=limit)


@router.get("/categories/{category_id}", response_model=CategoryResponse)
async def get_category(
    category_id: str,
    service: CatalogService = get_catalog_service_depends,
):
    """Get a category by ID."""
    category = await service.get_category(category_id)
    if not category:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Category not found",
        )
    return category


# Product endpoints
@router.post("/products", response_model=ProductResponse)
async def create_product(
    request: Request,
    product_data: ProductCreate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Create a new product."""
    # Verify user has permission
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.create_product(product_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    service: CatalogService = get_catalog_service_depends,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    merchant_id: str | None = None,
    category_id: str | None = None,
    status: str | None = Query(None, pattern="^(draft|active|suspended)$"),
    q: str | None = Query(None, description="Free-text search query (matches title, slug, description)"),
    price_min: int | None = Query(None, ge=0, description="Minimum price filter (inclusive, minor units)"),
    price_max: int | None = Query(None, ge=0, description="Maximum price filter (inclusive, minor units)"),
    currency: str | None = Query(None, min_length=3, max_length=3, description="Currency code filter (ISO 4217)"),
):
    """List products with optional filtering and free-text search."""
    return await service.list_products(
        skip=skip,
        limit=limit,
        merchant_id=merchant_id,
        category_id=category_id,
        status=status,
        search_query=q,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
    )


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    service: CatalogService = get_catalog_service_depends,
):
    """Get a product by ID."""
    product = await service.get_product(product_id)

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found",
        )

    return product


# Product Variant endpoints
@router.post(
    "/products/{product_id}/variants",
    response_model=ProductVariantResponse,
)
async def create_product_variant(
    request: Request,
    product_id: str,
    variant_data: ProductVariantCreate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Create a new product variant."""
    # Verify user has permission
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.create_product_variant(product_id, variant_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


# Inventory endpoints
@router.put("/inventory/{variant_id}")
async def update_inventory(
    request: Request,
    variant_id: str,
    inventory_data: InventoryUpdate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Update inventory levels for a product variant."""
    # Verify user has permission
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.update_inventory(variant_id, inventory_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data
    )
    return response_data


# Product Variant endpoints
@router.get("/products/{product_id}/variants", response_model=list[ProductVariantResponse])
async def list_product_variants(
    product_id: str,
    service: CatalogService = get_catalog_service_depends,
):
    """List all variants for a product."""
    try:
        variants = await service.list_product_variants(product_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    return variants


@router.get("/variants/sku/{sku}", response_model=ProductVariantResponse)
async def get_variant_by_sku(
    sku: str,
    service: CatalogService = get_catalog_service_depends,
):
    """Get a product variant by SKU."""
    variant = await service.get_variant_by_sku(sku)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )
    return variant


@router.get("/variants/product/sku/{sku}", response_model=ProductResponse)
async def get_product_by_variant_sku(
    sku: str,
    service: CatalogService = get_catalog_service_depends,
):
    """Get a product by its variant SKU."""
    product = await service.get_product_by_variant_sku(sku)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found for variant SKU",
        )
    return product


# Include the router in the main app
def get_router():
    return router

