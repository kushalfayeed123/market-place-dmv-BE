# app/modules/ledger/service/__init__.py
"""
Ledger service layer.
Provides abstract and concrete implementations for ledger operations.
"""

from app.modules.ledger.service.base import LedgerService
from app.modules.ledger.service.dependency import get_ledger_service
from app.modules.ledger.service.implementation import LedgerServiceImpl

__all__ = ["LedgerService", "LedgerServiceImpl", "get_ledger_service"]
