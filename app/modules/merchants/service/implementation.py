# app/modules/merchants/service/implementation.py
"""
Concrete implementation of the merchant service.
Handles database operations for merchants using SQLAlchemy.
"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    to_uuid,
)
from app.models.merchant import KycStatus, Merchant
from app.models.merchant_payout_account import MerchantPayoutAccount
from app.modules.merchants.service.base import MerchantService
from app.schemas.merchants import (
    MerchantCreate,
    MerchantPayoutAccountCreate,
    MerchantPayoutAccountResponse,
    MerchantPayoutAccountUpdate,
    MerchantResponse,
    MerchantUpdate,
)


class MerchantServiceImpl(MerchantService):
    """
    Database-backed implementation of MerchantService.
    
    This class encapsulates all database operations for merchants,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def create_merchant(self, merchant_data: MerchantCreate) -> MerchantResponse:
        """
        Create a new merchant in the database.
        
        Args:
            merchant_data: The merchant data to create.
            
        Returns:
            The created merchant response.
        """
        # Convert   schema enum to model enum, default to PENDING if not provided
        if merchant_data.kyc_status:
            kyc_status = KycStatus(merchant_data.kyc_status.value)
        else:
            kyc_status = KycStatus.PENDING

        new_merchant = Merchant(
            owner_user_id=to_uuid(merchant_data.owner_user_id),
            business_name=merchant_data.business_name,
            slug=merchant_data.slug,
            kyc_status=kyc_status,
            kyc_provider_ref=merchant_data.kyc_provider_ref,
            commission_plan_id=to_uuid(merchant_data.commission_plan_id),
            # Address fields
            address_line1=merchant_data.address_line1,
            address_line2=merchant_data.address_line2,
            city=merchant_data.city,
            state=merchant_data.state,
            postal_code=merchant_data.postal_code,
            country=merchant_data.country,
        )

        self._db.add(new_merchant)
        await self._db.commit()
        await self._db.refresh(new_merchant)

        return self._to_response(new_merchant)

    async def list_merchants(self, skip: int = 0, limit: int = 100) -> list[MerchantResponse]:
        """
        List merchants with pagination from the database.
        
        Args:
            skip: Number of records to skip.
            limit: Maximum number of records to return.
            
        Returns:
            List of merchant responses.
        """
        result = await self._db.execute(
            select(Merchant).offset(skip).limit(limit)
        )
        merchants = result.scalars().all()

        return [self._to_response(merchant) for merchant in merchants]

    async def get_merchant(self, merchant_id: str) -> MerchantResponse | None:
        """
        Get a merchant by ID from the database.
        
        Args:
            merchant_id: The unique identifier of the merchant.
            
        Returns:
            The merchant response if found, None otherwise.
        """
        result = await self._db.execute(
            select(Merchant).where(Merchant.id == merchant_id)
        )
        merchant = result.scalar_one_or_none()

        if merchant is None:
            return None

        return self._to_response(merchant)

    @staticmethod
    def _to_response(merchant: Merchant) -> MerchantResponse:
        """
        Convert a Merchant model instance to a MerchantResponse schema.
        
        Args:
            merchant: The SQLAlchemy Merchant model instance.
            
        Returns:
            The merchant response schema.
        """
        return MerchantResponse(
            id=str(merchant.id),
            owner_user_id=str(merchant.owner_user_id),
            business_name=merchant.business_name,
            slug=merchant.slug,
            kyc_status=merchant.kyc_status.value if merchant.kyc_status else None,
            kyc_provider_ref=merchant.kyc_provider_ref,
            commission_plan_id=str(merchant.commission_plan_id),
            address_line1=merchant.address_line1,
            address_line2=merchant.address_line2,
            city=merchant.city,
            state=merchant.state,
            postal_code=merchant.postal_code,
            country=merchant.country,
            created_at=merchant.created_at,
            updated_at=merchant.updated_at,
        )
