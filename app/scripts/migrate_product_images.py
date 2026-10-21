# app/scripts/migrate_product_images.py
"""
One-time migration script: move product images from local disk to S3.

Usage:
    python -m app.scripts.migrate_product_images

The script:
1. Finds all Product rows whose ``urls`` contain local file paths (e.g. ``/uploads/...``).
2. For each image, reads the byte blob from the local filesystem.
3. Uploads via ``DocumentService.migrate_product_image`` (which calls S3).
4. Rewrites ``Product.urls`` to point to the new S3 CDN URLs.
5. Deletes the local file after successful upload.

Environment:
    The script reads ``MEDIA_ROOT`` (default: ``app/static/uploads``) to resolve
    where local image files live on disk.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from sqlalchemy import select, update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.product import Product

logger = logging.getLogger(__name__)

# Default local media directory
MEDIA_ROOT = Path(__file__).resolve().parents[2] / "static" / "uploads"


def _is_local_url(url: str) -> bool:
    """Return True if *url* looks like a local server path, not an S3/CDN URL."""
    if not url:
        return False
    # Local URLs start with /uploads/ or the MEDIA_ROOT path
    if url.startswith("/uploads/") or url.startswith("/static/uploads/"):
        return True
    # Also catch absolute paths on disk
    if url.startswith(str(MEDIA_ROOT)) or url.startswith(str(Path.cwd())):
        return True
    return False


def _resolve_local_path(url: str) -> Path | None:
    """Resolve a local URL to a filesystem path under MEDIA_ROOT."""
    # Strip leading slash and any /uploads or /static/uploads prefix
    clean = url.lstrip("/")
    for prefix in ("uploads/", "static/uploads/"):
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break
    path = MEDIA_ROOT / clean
    return path if path.exists() else None


async def _migrate_product(
    service, db_session, product: Product
) -> int:
    """Migrate all local image URLs for a single product. Returns count migrated."""
    from app.core.storage import upload_file_from_bytes
    from app.core.config import settings as _s

    try:
        urls = json.loads(product.urls) if product.urls else []
    except (json.JSONDecodeError, TypeError):
        urls = []

    new_urls: list[str] = []
    migrated = 0

    for old_url in urls:
        if not _is_local_url(old_url):
            # Already on S3 or external — keep as-is.
            new_urls.append(old_url)
            continue

        local_path = _resolve_local_path(old_url)
        if local_path is None:
            logger.warning("Local file not found for %s: %s", product.id, old_url)
            new_urls.append(old_url)
            continue

        # Read the file bytes
        file_data = local_path.read_bytes()
        original_filename = local_path.name

        # Upload via the service (creates a Document row + S3 object)
        cdn_url = await service.migrate_product_image(
            product_id_str=str(product.id),
            file_data=file_data,
            original_filename=original_filename,
        )
        new_urls.append(cdn_url)
        migrated += 1

        # Optionally delete the local file after successful upload
        try:
            local_path.unlink()
            logger.info("Deleted local file after migration: %s", local_path)
        except OSError:
            pass  # File may have already been removed

    if migrated > 0:
        # Update the Product.urls column
        await db_session.execute(
            update(Product)
            .where(Product.id == product.id)
            .values(urls=json.dumps(new_urls))
        )
        await db_session.commit()
        logger.info(
            "Migrated %d image(s) for product %s -> %s",
            migrated, product.id, new_urls,
        )

    return migrated


async def run_migration() -> None:
    """Entry point: scan all products with local image URLs and migrate them."""
    from app.modules.documents.service import DocumentService

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Starting product image migration (MEDIA_ROOT=%s)", MEDIA_ROOT)

    async with AsyncSessionLocal() as db:
        service = DocumentService(db)

        result = await db.execute(
            select(Product).where(Product.urls != "[]")
        )
        products = result.scalars().all()

        total_migrated = 0
        for product in products:
            try:
                count = await _migrate_product(service, db, product)
                total_migrated += count
            except Exception:
                logger.exception("Failed to migrate product %s", product.id)

        logger.info("Migration complete: %d image(s) migrated", total_migrated)


def main() -> None:
    """Synchronous wrapper for the async migration."""
    asyncio.run(run_migration())


if __name__ == "__main__":
    main()
