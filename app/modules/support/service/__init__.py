# app/modules/support/service/__init__.py
"""Support ticket service package."""

from .base import SupportService
from .dependency import get_support_service

__all__ = ["SupportService", "get_support_service"]
