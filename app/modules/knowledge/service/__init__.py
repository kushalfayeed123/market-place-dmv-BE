# app/modules/knowledge/service/__init__.py
"""Knowledge document service package."""

from .base import KnowledgeService
from .dependency import get_knowledge_service

__all__ = ["KnowledgeService", "get_knowledge_service"]
