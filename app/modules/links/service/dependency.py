# app/modules/links/service/dependency.py
"""Dependency injection for the share-link service."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.links.service.implementation import LinksServiceImpl

get_db_depends = Depends(get_db)


def get_links_service(db: AsyncSession = get_db_depends) -> LinksServiceImpl:
    """Factory returning a LinksServiceImpl bound to the request's DB session."""
    return LinksServiceImpl(db)
