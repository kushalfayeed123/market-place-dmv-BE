# app/modules/support/service/dependency.py
"""Dependency injection for the support ticket service."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.support.service.base import SupportService
from app.modules.support.service.implementation import SupportServiceImpl

get_db_depends = Depends(get_db)


def get_support_service(db: AsyncSession = get_db_depends) -> SupportService:
    return SupportServiceImpl(db)
