# app/modules/catalog/router.py
"""
Catalog router handling products, categories, and inventory.
Communicates with the service layer via the CatalogService abstraction.
"""


from app.core.config import settings
from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.security import get_current_active_user, to_uuid
from app.core.storage import presign_download
from app.db.session import get_db
from app.models.digital_asset import DigitalAsset
from app.models.merchant import Merchant
from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.store import Store
from app.models.user import UserRole
from app.modules.catalog.service.base import CatalogService
from app.modules.catalog.service.dependency import get_catalog_service
from app.modules.documents.service import DocumentService
from app.schemas.catalog import (
    CategoryCreate,
    CategoryResponse,
    DigitalProductFileDownloadResponse,
    DigitalProductFileResponse,
    InventoryUpdate,
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    ProductVariantCreate,
    ProductVariantResponse,
    ProductVariantUpdate,
)
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_active_user_depends = Depends(get_current_active_user)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_catalog_service_depends = Depends(get_catalog_service)
get_db_depends = Depends(get_db)


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
    db: AsyncSession = get_db_depends,
):
    """Create a new product.

    If ``merchant_id`` / ``store_id`` are omitted they are derived from the
    authenticated user's merchant and primary store.  ``slug`` is auto-generated
    from ``title`` when not supplied.
    """
    # Verify user has permission
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    # ── Derive merchant_id from the authenticated user when not supplied ──
    if product_data.merchant_id is None:
        if current_user.role.value == UserRole.PLATFORM_ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="merchant_id is required when creating as platform_admin",
            )
        result = await db.execute(
            select(Merchant).where(Merchant.owner_user_id == current_user.id)
        )
        merchant = result.scalar_one_or_none()
        if merchant is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No merchant account found for this user",
            )
        product_data = product_data.model_copy(update={"merchant_id": str(merchant.id)})

    # ── Derive store_id (primary store) when not supplied ──
    if product_data.store_id is None:
        result = await db.execute(
            select(Store).where(Store.merchant_id == to_uuid(product_data.merchant_id)).limit(1)
        )
        store = result.scalar_one_or_none()
        if store is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No store found for merchant '{product_data.merchant_id}'",
            )
        product_data = product_data.model_copy(update={"store_id": str(store.id)})

    # ── Auto-generate slug from title when not supplied ──
    if product_data.slug is None:
        import re
        base = re.sub(r"[^a-zA-Z0-9]+", "-", product_data.title.lower()).strip("-")
        slug = base[:100] if base else "product"
        product_data = product_data.model_copy(update={"slug": slug})

    try:
        response_data = await service.create_product(product_data)
    except ValueError as e:
        # Attribute-schema validation errors are "missing required fields"
        # â€” signal them as 422 so the frontend can prompt the user to fill
        # in the required attributes.
        detail = str(e)
        if detail.startswith("Missing required attribute"):
            code = status.HTTP_422_UNPROCESSABLE_ENTITY
        else:
            code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=code,
            detail=detail,
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
    product_type: str | None = Query(
        None, description="Filter to products assigned to this type (e.g. 'digital')."
    ),
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
        product_type=product_type,
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


# ── Product update (partial PATCH) ──
@router.patch(
    "/products/{product_id}",
    response_model=ProductResponse,
)
async def update_product(
    request: Request,
    product_id: str,
    product_data: ProductUpdate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Partially update a product.

    Only the merchant that owns the product (or a platform admin) may update it.
    Only fields that are non-``None`` on the request body are applied.
    """
    # Permission: merchant_owner / merchant_staff / platform_admin
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.update_product(product_id, product_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK,
        response_body=response_data.model_dump(),
    )
    return response_data


# ── Product likes ──
@router.post("/products/{product_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def like_product(
    request: Request,
    product_id: str,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
):
    """Like a product (idempotent). Requires authentication."""
    try:
        await service.like_product(current_user.id, product_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_204_NO_CONTENT,
    )
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@router.delete("/products/{product_id}/like", status_code=status.HTTP_204_NO_CONTENT)
async def unlike_product(
    request: Request,
    product_id: str,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
):
    """Remove a like from a product. Requires authentication."""
    try:
        await service.unlike_product(current_user.id, product_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_204_NO_CONTENT,
    )
    return JSONResponse(status_code=status.HTTP_204_NO_CONTENT, content=None)


@router.get("/products/{product_id}/likes")
async def get_product_likes(
    product_id: str,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
):
    """Get the like count for a product and whether the current user has liked it."""
    try:
        result = await service.get_product_like_count(product_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    return result


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


@router.get(
    "/products/{product_id}/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def get_product_variant(
    product_id: str,
    variant_id: str,
    service: CatalogService = get_catalog_service_depends,
):
    """Get a single product variant by ID."""
    variant = await service.get_product_variant(product_id, variant_id)
    if not variant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Variant not found",
        )
    return variant


@router.patch(
    "/products/{product_id}/variants/{variant_id}",
    response_model=ProductVariantResponse,
)
async def update_product_variant(
    request: Request,
    product_id: str,
    variant_id: str,
    variant_data: ProductVariantUpdate,
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """Partially update a product variant (sku, attributes, price override, stock policy)."""
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    try:
        response_data = await service.update_product_variant(product_id, variant_id, variant_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data.model_dump()
    )
    return response_data


# Product image upload — part of the product creation flow.
@router.post(
    "/products/{product_id}/images",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
)
async def upload_product_image(
    request: Request,
    product_id: str,
    image: UploadFile = File(..., description="Product image (PNG/JPG/WebP/GIF, max 5MB)"),
    current_user: dict = get_current_active_user_depends,
    service: CatalogService = get_catalog_service_depends,
    db: AsyncSession = get_db_depends,
):
    """Upload a product image to S3 and append its URL to the product's `urls`.

    Workflow: create the product first (`POST /products`), then call this endpoint
    one or more times to add images. Each image is validated, uploaded directly to
    the S3 bucket (not the local filesystem), and the resulting public URL is
    appended to `Product.urls` via the documents subsystem's domain-linking logic.
    A product may have multiple images — call this endpoint repeatedly.
    """
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )

    content_type = image.content_type or ""
    allowed = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    ext = allowed.get(content_type)
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image (PNG/JPG/Webp/GIF)",
        )

    contents = await image.read()
    max_bytes = 5 * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image too large (max {max_bytes // (1024 * 1024)}MB)",
        )
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    # Upload to S3 via the documents subsystem.  This creates a COMPLETE
    # Document record, pushes the bytes to S3 with ``ACL: public-read``,
    # and links the resulting public URL to the product's `urls` list
    # via `_link_to_domain`.
    doc_service = DocumentService(db)
    try:
        await doc_service.upload_product_image(
            product_id_str=product_id,
            file_data=contents,
            original_filename=image.filename or "image",
            content_type=content_type,
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )

    # Return the updated product (with the new image URL in `urls`).
    updated = await service.get_product(product_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product {product_id} not found",
        )
    return updated


@router.post(
    "/product-file-upload",
    response_model=DigitalProductFileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_file(
    product_id: str = Form(...),
    fulfillment: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Receive digital content via multipart and store it privately on the backend."""
    role = current_user.role.value
    if role not in ["merchant_owner", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the product's merchant owner can upload digital content.",
        )
    if fulfillment != "digital":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Digital content requires fulfillment='digital'.",
        )

    try:
        product_uuid = to_uuid(product_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        ) from exc

    result = await db.execute(select(Product).where(Product.id == product_uuid))
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    if role != "platform_admin":
        ownership = await db.execute(
            select(Merchant.id).where(
                Merchant.id == product.merchant_id,
                Merchant.owner_user_id == current_user.id,
            )
        )
        if ownership.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to update this product.",
            )

    max_bytes = settings.S3_MAX_UPLOAD_MB * 1024 * 1024
    file_data = await file.read(max_bytes + 1)
    if len(file_data) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds max upload size of {settings.S3_MAX_UPLOAD_MB}MB.",
        )
    return await DocumentService(db).upload_digital_product_file(
        product_id_str=product_id,
        file_data=file_data,
        original_filename=file.filename or "",
    )


@router.get(
    "/products/{product_id}/digital-file",
    response_model=DigitalProductFileDownloadResponse,
)
async def get_purchased_product_file(
    product_id: str,
    current_user: dict = get_current_active_user_depends,
    db: AsyncSession = get_db_depends,
):
    """Return a short-lived file URL only to a buyer who paid for the product."""
    if current_user.role.value != "buyer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Digital product content is available to purchasing buyers only.",
        )
    try:
        product_uuid = to_uuid(product_id)
        buyer_uuid = to_uuid(str(current_user.id))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Digital product file not found.",
        ) from exc

    purchase = await db.execute(
        select(OrderItem.id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(
            OrderItem.product_id == product_uuid,
            Order.buyer_id == buyer_uuid,
            or_(
                Order.status.in_([
                    OrderStatus.PAID.value,
                    OrderStatus.PARTIALLY_FULFILLED.value,
                    OrderStatus.SHIPPED.value,
                    OrderStatus.FULFILLED.value,
                ]),
                and_(
                    Order.status == OrderStatus.ACCEPTED.value,
                    select(PaymentTransaction.id)
                    .where(
                        PaymentTransaction.order_id == Order.id,
                        PaymentTransaction.status == "success",
                    )
                    .exists(),
                ),
            ),
        )
        .limit(1)
    )
    if purchase.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Digital product file not found.",
        )

    asset_result = await db.execute(
        select(DigitalAsset).where(
            DigitalAsset.product_id == product_uuid,
            DigitalAsset.variant_id.is_(None),
        )
    )
    asset = asset_result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Digital product file not found.",
        )

    from pathlib import PurePosixPath
    import mimetypes

    filename = PurePosixPath(asset.storage_key).name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    file_format = PurePosixPath(filename).suffix.lower().lstrip(".")
    url = await run_in_threadpool(
        presign_download,
        bucket=settings.S3_BUCKET,
        key=asset.storage_key,
        ttl_seconds=settings.S3_DOWNLOAD_URL_TTL_SECONDS,
        inline=True,
    )
    return {
        "download_url": url,
        "expires_in": settings.S3_DOWNLOAD_URL_TTL_SECONDS,
        "filename": filename,
        "content_type": content_type,
        "format": file_format,
    }


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
