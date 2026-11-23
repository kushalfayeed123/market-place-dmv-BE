# app/modules/links/service/implementation.py
"""Concrete implementation of the share-link service."""

import json
import secrets
import string
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import to_uuid
from app.models.merchant import Merchant
from app.models.product import Product, product_product_types
from app.models.product_variant import ProductVariant
from app.models.store import Store
from app.models.share_link import ShareLink, share_link_products
from app.schemas.share_link import (
    ShareLinkCreate,
    ShareLinkResponse,
    ShareLinkResolveResponse,
    ShareLinkStoreInfo,
    ShareLinkResolvedProduct,
)


class LinksServiceImpl:
    """Database-backed implementation of ShareLinkService."""

    def __init__(self, db: AsyncSession):
        self._db = db

    @staticmethod
    def _to_response(link: ShareLink) -> ShareLinkResponse:
        """Serialize a ShareLink row, building the public storefront URL."""
        from app.core.config import settings

        base = (settings.PUBLIC_BASE_URL or settings.FRONTEND_URL).rstrip("/")
        try:
            product_ids = json.loads(link.product_ids) if link.product_ids else []
        except (json.JSONDecodeError, TypeError):
            product_ids = []
        return ShareLinkResponse(
            id=str(link.id),
            code=link.code,
            merchant_id=str(link.merchant_id),
            store_id=str(link.store_id),
            title=link.title,
            product_ids=product_ids if isinstance(product_ids, list) else [],
            is_active=link.is_active,
            url=f"{base}/s/{link.code}",
            created_at=link.created_at,
            updated_at=link.updated_at,
        )

    async def create_link(
        self, merchant_id: str, data: ShareLinkCreate
    ) -> ShareLinkResponse:
        """Create a share link owned by the given merchant."""
        # Validate the store belongs to the merchant.
        store = (
            await self._db.execute(
                select(Store).where(
                    Store.id == to_uuid(data.store_id),
                    Store.merchant_id == to_uuid(merchant_id),
                )
            )
        ).scalar_one_or_none()
        if not store:
            raise ValueError("Store not found or does not belong to this merchant")

        # Validate that every requested product belongs to the same merchant,
        # so a link can never expose another merchant's catalog.
        product_uuids: list = []
        if data.product_ids:
            seen: set[str] = set()
            for pid in data.product_ids:
                try:
                    puuid = to_uuid(pid)
                except ValueError:
                    raise ValueError(f"Invalid product id: '{pid}'")
                if str(puuid) in seen:
                    continue
                seen.add(str(puuid))
                product_uuids.append(puuid)
            if product_uuids:
                found = (
                    await self._db.execute(
                        select(Product.id).where(
                            Product.id.in_(product_uuids),
                            Product.merchant_id == to_uuid(merchant_id),
                            Product.store_id == to_uuid(data.store_id),
                        )
                    )
                ).scalars().all()
                if len(found) != len(product_uuids):
                    raise ValueError("One or more products were not found in this store")
            product_ids_json = json.dumps([str(u) for u in product_uuids])
        else:
            product_ids_json = "[]"

        # Generate a short, URL-safe code
        code = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

        new_link = ShareLink(
            code=code,
            merchant_id=to_uuid(merchant_id),
            store_id=to_uuid(data.store_id),
            title=data.title,
            product_ids=product_ids_json,
        )

        self._db.add(new_link)
        await self._db.flush()

        # Persist the link -> product association rows for product-set links.
        if product_uuids:
            await self._db.execute(
                insert(share_link_products),
                [{"link_id": new_link.id, "product_id": puuid} for puuid in product_uuids],
            )

        await self._db.commit()
        await self._db.refresh(new_link)

        return self._to_response(new_link)

    async def list_links(
        self, merchant_id: str, skip: int = 0, limit: int = 100
    ) -> list[ShareLinkResponse]:
        """List share links belonging to a merchant."""
        result = await self._db.execute(
            select(ShareLink)
            .where(ShareLink.merchant_id == to_uuid(merchant_id))
            .order_by(ShareLink.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        links = result.scalars().all()
        return [self._to_response(link) for link in links]

    async def get_link(self, link_id: str, merchant_id: str) -> ShareLinkResponse | None:
        """Get one of a merchant's links by id."""
        result = await self._db.execute(
            select(ShareLink).where(ShareLink.id == to_uuid(link_id), ShareLink.merchant_id == to_uuid(merchant_id))
        )
        link = result.scalar_one_or_none()
        if not link:
            return None
        return self._to_response(link)

    async def deactivate_link(self, link_id: str, merchant_id: str) -> ShareLinkResponse | None:
        """Disable a link so it no longer resolves publicly."""
        result = await self._db.execute(
            select(ShareLink).where(ShareLink.id == to_uuid(link_id), ShareLink.merchant_id == to_uuid(merchant_id))
        )
        link = result.scalar_one_or_none()
        if not link:
            return None

        link.is_active = "inactive"
        await self._db.commit()
        await self._db.refresh(link)

        return self._to_response(link)

    async def resolve_public(self, code: str) -> ShareLinkResolveResponse | None:
        """Public resolution of a link code: store info plus the products it exposes."""
        result = await self._db.execute(select(ShareLink).where(ShareLink.code == code, ShareLink.is_active == "active"))
        link = result.scalar_one_or_none()
        if not link:
            return None

        row = await self._db.execute(
            select(Store, Merchant)
            .join(Merchant, Store.merchant_id == Merchant.id)
            .where(Store.id == link.store_id)
        )
        merchant_row = row.first()
        if not merchant_row:
            return None
        store_obj, merchant_obj = merchant_row

        # Determine kind: store link vs product-set link. A product-set link
        # resolves to exactly those products; a store link resolves to all
        # active products in the store.
        product_ids = json.loads(link.product_ids) if link.product_ids else []
        kind = "products" if product_ids else "store"

        # Build store info (branding is a JSON-encoded Text column)
        raw_branding = store_obj.branding
        try:
            branding = json.loads(raw_branding) if isinstance(raw_branding, str) else (raw_branding or {})
        except (json.JSONDecodeError, TypeError):
            branding = {}
        if not isinstance(branding, dict):
            branding = {}

        store_info = ShareLinkStoreInfo(
            id=str(store_obj.id),
            merchant_id=str(merchant_obj.id),
            name=merchant_obj.business_name,
            slug=store_obj.slug,
            branding=branding,
        )

        # Build product list
        products: list[ShareLinkResolvedProduct] = []
        if kind == "products":
            # Product-set link: visitors land on a listing with just these products.
            prod_result = await self._db.execute(
                select(Product)
                .join(share_link_products, share_link_products.c.product_id == Product.id)
                .where(share_link_products.c.link_id == link.id, Product.status == "active")
            )
            products_rows = prod_result.scalars().all()
        else:
            # Store link: visitors see every active product in the store.
            prod_result = await self._db.execute(
                select(Product)
                .where(Product.store_id == link.store_id, Product.status == "active")
                .limit(50)
            )
            products_rows = prod_result.scalars().all()

        for p in products_rows:
            variants_result = await self._db.execute(
                select(ProductVariant).where(ProductVariant.product_id == p.id)
            )
            variants = []
            for v in variants_result.scalars().all():
                raw_attrs = v.attributes
                try:
                    attrs = json.loads(raw_attrs) if isinstance(raw_attrs, str) else (raw_attrs or {})
                except (json.JSONDecodeError, TypeError):
                    attrs = {}
                if not isinstance(attrs, dict):
                    attrs = {}
                variants.append(
                    {
                        "id": str(v.id),
                        "sku": v.sku or "",
                        "price_override_amount": v.price_override_amount,
                        "price_override_currency": v.price_override_currency,
                        "price": {
                            "amount": int(v.price_override_amount or p.base_price_amount or 0),
                            "currency": v.price_override_currency or p.base_price_currency or "NGN",
                        },
                        "inventory_policy": v.inventory_policy or "tracked",
                        "attributes": attrs,
                    }
                )

            # Product types live in the product_product_types association table.
            types_result = await self._db.execute(
                select(product_product_types.c.product_type).where(
                    product_product_types.c.product_id == p.id
                )
            )
            product_types = [row[0] for row in types_result.all()]

            # urls is a JSON-encoded Text column.
            raw_urls = p.urls
            try:
                urls_list = json.loads(raw_urls) if isinstance(raw_urls, str) else (raw_urls or [])
            except (json.JSONDecodeError, TypeError):
                urls_list = []
            if not isinstance(urls_list, list):
                urls_list = []

            products.append(
                ShareLinkResolvedProduct(
                    id=str(p.id),
                    merchant_id=str(p.merchant_id),
                    store_id=str(p.store_id),
                    store_name=store_obj.name,
                    title=p.title,
                    slug=p.slug,
                    description=p.description,
                    fulfillment_type=p.fulfillment_type or "physical",
                    product_types=product_types or ([p.fulfillment_type] if p.fulfillment_type else []),
                    status=p.status or "active",
                    base_price_amount=p.base_price_amount or 0,
                    base_price_currency=p.base_price_currency or "NGN",
                    urls=urls_list,
                    variants=variants,
                )
            )

        from app.core.config import settings
        base = (settings.PUBLIC_BASE_URL or settings.FRONTEND_URL).rstrip("/")

        return ShareLinkResolveResponse(
            code=link.code,
            kind=kind,
            title=link.title,
            url=f"{base}/s/{link.code}",
            store=store_info,
            products=products,
        )