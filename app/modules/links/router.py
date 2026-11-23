# app/modules/links/router.py
"""
Share links router.

Merchant endpoints (auth required):
  POST   /links/                    create a store or product-set share link
  GET    /links/                    list the merchant's links
  GET    /links/{link_id}           get one link
  POST   /links/{link_id}/deactivate  disable a link

Public endpoint (no auth):
  GET    /links/public/{code}       resolve a link code -> store + products
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user, to_uuid
from app.db.session import get_db
from app.models.merchant import Merchant
from app.modules.links.service.dependency import get_links_service
from app.modules.links.service.implementation import LinksServiceImpl
from app.schemas.share_link import (
    ShareLinkCreate,
    ShareLinkResolveResponse,
    ShareLinkResponse,
)

router = APIRouter()

get_current_active_user_depends = Depends(get_current_active_user)
get_links_service_depends = Depends(get_links_service)
get_db_depends = Depends(get_db)


async def _merchant_id_for_user(current_user, db: AsyncSession) -> str:
    """Resolve the merchant owned by the current (non-admin) user."""
    result = await db.execute(
        select(Merchant).where(Merchant.owner_user_id == to_uuid(current_user.id))
    )
    merchant = result.scalar_one_or_none()
    if not merchant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No merchant account found for this user",
        )
    return str(merchant.id)


@router.post("/", response_model=ShareLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_link(
    data: ShareLinkCreate,
    merchant_id: str | None = Query(None, description="Required for platform_admin; derived for merchant owners/staff."),
    current_user: dict = get_current_active_user_depends,
    service: LinksServiceImpl = get_links_service_depends,
    db: AsyncSession = get_db_depends,
):
    """Create a share link (store-wide or a product set) for a merchant."""
    if current_user.role.value not in ["merchant_owner", "merchant_staff", "platform_admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if current_user.role.value == "platform_admin":
        if not merchant_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="platform_admin must pass merchant_id")
        mid = merchant_id
    else:
        mid = await _merchant_id_for_user(current_user, db)

    try:
        return await service.create_link(mid, data)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=list[ShareLinkResponse])
async def list_links(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = get_current_active_user_depends,
    service: LinksServiceImpl = get_links_service_depends,
    db: AsyncSession = get_db_depends,
):
    """List share links for the authenticated merchant."""
    merchant_id = await _merchant_id_for_user(current_user, db)
    return await service.list_links(merchant_id, skip=skip, limit=limit)


@router.get("/{link_id}", response_model=ShareLinkResponse)
async def get_link(
    link_id: str,
    current_user: dict = get_current_active_user_depends,
    service: LinksServiceImpl = get_links_service_depends,
    db: AsyncSession = get_db_depends,
):
    merchant_id = await _merchant_id_for_user(current_user, db)
    link = await service.get_link(link_id, merchant_id)
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    return link


@router.post("/{link_id}/deactivate", response_model=ShareLinkResponse)
async def deactivate_link(
    link_id: str,
    current_user: dict = get_current_active_user_depends,
    service: LinksServiceImpl = get_links_service_depends,
    db: AsyncSession = get_db_depends,
):
    merchant_id = await _merchant_id_for_user(current_user, db)
    link = await service.deactivate_link(link_id, merchant_id)
    if not link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    return link


@router.get("/public/{code}", response_model=ShareLinkResolveResponse)
async def resolve_public_link(
    code: str,
    service: LinksServiceImpl = get_links_service_depends,
):
    """Public: resolve a share-link code to the store and its products."""
    resolved = await service.resolve_public(code)
    if not resolved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found or inactive")
    return resolved


def get_router():
    return router
