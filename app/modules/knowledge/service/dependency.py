# app/modules/knowledge/service/dependency.py
"""Dependency injection for the knowledge document service."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.modules.knowledge.service.base import KnowledgeService
from app.modules.knowledge.service.implementation import KnowledgeServiceImpl

get_db_depends = Depends(get_db)


def get_knowledge_service(db: AsyncSession = get_db_depends) -> KnowledgeService:
    return KnowledgeServiceImpl(db)
