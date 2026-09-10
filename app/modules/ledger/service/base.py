# app/modules/ledger/service/base.py
"""
Abstract base class for ledger service.
Defines the interface that all ledger service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.ledger import (
    LedgerBalanceResponse,
    LedgerEntryResponse,
)


class LedgerService(ABC):
    """
    Abstract interface for ledger operations.
    
    This class defines the contract for any ledger service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def list_entries(
        self,
        skip: int = 0,
        limit: int = 100,
        merchant_id: str | None = None,
        entry_type: str | None = None,
        account_type: str | None = None,
        direction: str | None = None,
        min_amount: int | None = None,
        max_amount: int | None = None,
        order_id: str | None = None,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> list[LedgerEntryResponse]:
        """
        List ledger entries with filtering and access control.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            merchant_id: Filter by merchant ID.
            entry_type: Filter by entry type.
            account_type: Filter by account type.
            direction: Filter by direction (credit/debit).
            min_amount: Filter by minimum amount.
            max_amount: Filter by maximum amount.
            order_id: Filter by order ID.
            user_id: Current user ID for access control.
            user_role: Current user role for access control.
            
        Returns:
            List of ledger entry responses.
        """
        ...

    @abstractmethod
    async def get_entry(self, entry_id: str) -> LedgerEntryResponse | None:
        """
        Get a ledger entry by ID.
        
        Args:
            entry_id: The ledger entry ID.
            
        Returns:
            The ledger entry response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_balance(
        self,
        merchant_id: str,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> LedgerBalanceResponse:
        """
        Get the balance for a merchant.
        
        Args:
            merchant_id: The merchant ID.
            user_id: Current user ID for access control.
            user_role: Current user role for access control.
            
        Returns:
            The ledger balance response.
            
        Raises:
            ValueError: If merchant not found.
            PermissionError: If user not authorized.
        """
        ...
