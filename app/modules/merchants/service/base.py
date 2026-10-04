# app/modules/merchants/service/base.py
"""
Abstract base class for merchant service.
Defines the interface that all merchant service implementations must follow.
"""

from abc import ABC, abstractmethod

from app.schemas.merchants import (
    MerchantCreate,
    MerchantPayoutAccountCreate,
    MerchantPayoutAccountResponse,
    MerchantPayoutAccountUpdate,
    MerchantResponse,
    MerchantUpdate,
)


class MerchantService(ABC):
    """
    Abstract interface for merchant operations.
    
    This class defines the contract for any merchant service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def create_merchant(self, merchant_data: MerchantCreate) -> MerchantResponse:
        """
        Create a new merchant.
        
        Args:
            merchant_data: The merchant data to create.
            
        Returns:
            The created merchant response.
            
        Raises:
            ValueError: If merchant data is invalid.
            RuntimeError: If creation fails.
        """
        ...

    @abstractmethod
    async def list_merchants(self, skip: int = 0, limit: int = 100) -> list[MerchantResponse]:
        """
        List merchants with pagination.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of merchant responses.
        """
        ...

    @abstractmethod
    async def get_merchant(self, merchant_id: str) -> MerchantResponse | None:
        """
        Get a merchant by ID.

        Args:
            merchant_id: The unique identifier of the merchant.

        Returns:
            The merchant response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def get_merchant_by_owner(self, user_id: str) -> MerchantResponse | None:
        """
        Get a merchant by the owner's user ID.

        Args:
            user_id: The owner's user ID.

        Returns:
            The merchant response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def update_merchant(
        self, merchant_id: str, data: MerchantUpdate
    ) -> MerchantResponse:
        """
        Partially update a merchant's information.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            data: The fields to update (all optional).
            
        Returns:
            The updated merchant response.
            
        Raises:
            ValueError: If the merchant is not found.
        """
        ...

    @abstractmethod
    async def create_payout_account(
        self, merchant_id: str, data: MerchantPayoutAccountCreate
    ) -> MerchantPayoutAccountResponse:
        """
        Create a new payout account for a merchant.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            data: The payout account data.
            
        Returns:
            The created payout account response.
            
        Raises:
            ValueError: If the merchant is not found.
        """
        ...

    @abstractmethod
    async def list_payout_accounts(
        self, merchant_id: str, skip: int = 0, limit: int = 100
    ) -> list[MerchantPayoutAccountResponse]:
        """
        List all payout accounts for a merchant.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of payout account responses.
        """
        ...

    @abstractmethod
    async def get_payout_account(
        self, merchant_id: str, payout_id: str
    ) -> MerchantPayoutAccountResponse | None:
        """
        Get a specific payout account for a merchant.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            payout_id: The unique identifier of the payout account.
            
        Returns:
            The payout account response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def update_payout_account(
        self, merchant_id: str, payout_id: str, data: MerchantPayoutAccountUpdate
    ) -> MerchantPayoutAccountResponse:
        """
        Partially update a payout account.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            payout_id: The unique identifier of the payout account.
            data: The fields to update (all optional).
            
        Returns:
            The updated payout account response.
            
        Raises:
            ValueError: If the payout account is not found.
        """
        ...

    @abstractmethod
    async def delete_payout_account(self, merchant_id: str, payout_id: str) -> None:
        """
        Deactivate (soft-delete) a payout account.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            payout_id: The unique identifier of the payout account.
            
        Raises:
            ValueError: If the payout account is not found.
        """
        ...
