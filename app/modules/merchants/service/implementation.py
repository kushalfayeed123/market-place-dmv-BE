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
from app.models.commission_plan import CommissionPlan
from app.models.merchant import KycStatus, Merchant
from app.models.merchant_payout_account import MerchantPayoutAccount
from app.models.store import Store
from app.modules.merchants.service.base import MerchantService
from app.schemas.merchants import (
    MerchantCreate,
    MerchantOnboard,
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

    async def create_merchant_for_user(
        self, user_id: str, data: MerchantOnboard
    ) -> MerchantResponse:
        """
        Create a merchant (and a primary store) for a specific user
        during the self-service onboarding flow.

        Args:
            user_id: The UUID of the owning user.
            data: The onboarding payload (business name, slug, …).

        Returns:
            The created merchant response.

        Raises:
            ValueError: If a merchant already exists for the user,
                        or if no default commission plan is configured.
        """
        owner_uuid = to_uuid(user_id)

        # Idempotency: refuse to create a second merchant for the same owner
        existing = await self._db.execute(
            select(Merchant).where(Merchant.owner_user_id == owner_uuid)
        )
        if existing.scalar_one_or_none() is not None:
            raise ValueError("A merchant already exists for this user")

        # Resolve the default commission plan
        plan_result = await self._db.execute(
            select(CommissionPlan).where(CommissionPlan.is_default == True)
        )
        default_plan = plan_result.scalar_one_or_none()
        if default_plan is None:
            raise ValueError("No default commission plan is configured")

        # Create the merchant entity
        new_merchant = Merchant(
            owner_user_id=owner_uuid,
            business_name=data.business_name,
            slug=data.slug,
            kyc_status=KycStatus.PENDING,
            commission_plan_id=default_plan.id,
            address_line1=data.address_line1,
            address_line2=data.address_line2,
            city=data.city,
            state=data.state,
            postal_code=data.postal_code,
            country=data.country,
        )
        self._db.add(new_merchant)
        await self._db.commit()
        await self._db.refresh(new_merchant)

        # Create a primary store so the merchant can immediately
        # accept product listings and orders.
        new_store = Store(
            merchant_id=new_merchant.id,
            name=data.business_name,
            slug=data.slug,
        )
        self._db.add(new_store)
        await self._db.commit()

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
            select(Merchant).where(Merchant.id == to_uuid(merchant_id))
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

    async def get_merchant_by_owner(self, user_id: str) -> MerchantResponse | None:
        """Get a merchant by the owner's user ID."""
        result = await self._db.execute(
            select(Merchant).where(Merchant.owner_user_id == to_uuid(user_id))
        )
        merchant = result.scalar_one_or_none()
        if merchant is None:
            return None
        return self._to_response(merchant)

    async def update_merchant(
        self, merchant_id: str, data: MerchantUpdate
    ) -> MerchantResponse:
        """Partially update a merchant."""
        result = await self._db.execute(
            select(Merchant).where(Merchant.id == merchant_id)
        )
        merchant = result.scalar_one_or_none()
        if merchant is None:
            raise ValueError("Merchant not found")
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(merchant, key, value)
        await self._db.commit()
        await self._db.refresh(merchant)
        return self._to_response(merchant)

    async def create_payout_account(
        self, merchant_id: str, data: MerchantPayoutAccountCreate
    ) -> MerchantPayoutAccountResponse:
        """Create a payout account for a merchant."""
        account = MerchantPayoutAccount(
            merchant_id=to_uuid(merchant_id),
            provider=data.provider,
            currency=data.currency,
            external_ref=data.external_ref,
            account_last4=data.account_last4,
            bank_name=data.bank_name,
            account_holder_name=data.account_holder_name,
            bank_code=data.bank_code,
            routing_number=data.routing_number,
            account_type=data.account_type,
            country=data.country,
        )
        self._db.add(account)
        await self._db.commit()
        await self._db.refresh(account)
        return self._to_payout_response(account)

    async def list_payout_accounts(
        self, merchant_id: str, skip: int = 0, limit: int = 100
    ) -> list[MerchantPayoutAccountResponse]:
        """List payout accounts for a merchant."""
        result = await self._db.execute(
            select(MerchantPayoutAccount)
            .where(MerchantPayoutAccount.merchant_id == to_uuid(merchant_id))
            .offset(skip)
            .limit(limit)
        )
        accounts = result.scalars().all()
        return [self._to_payout_response(a) for a in accounts]

    @staticmethod
    def _to_payout_response(account: MerchantPayoutAccount) -> MerchantPayoutAccountResponse:
        """Convert a MerchantPayoutAccount model to a response schema."""
        return MerchantPayoutAccountResponse(
            id=str(account.id),
            merchant_id=str(account.merchant_id),
            provider=account.provider,
            currency=account.currency,
            external_ref=account.external_ref,
            account_last4=account.account_last4,
            bank_name=account.bank_name,
            account_holder_name=account.account_holder_name,
            bank_code=account.bank_code,
            routing_number=account.routing_number,
            account_type=account.account_type,
            country=account.country,
            is_active=account.is_active,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    async def get_payout_account(
        self, merchant_id: str, payout_id: str
    ) -> MerchantPayoutAccountResponse | None:
        """Get a specific payout account."""
        result = await self._db.execute(
            select(MerchantPayoutAccount).where(
                MerchantPayoutAccount.id == to_uuid(payout_id),
                MerchantPayoutAccount.merchant_id == to_uuid(merchant_id),
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            return None
        return self._to_payout_response(account)

    async def update_payout_account(
        self, merchant_id: str, payout_id: str, data: MerchantPayoutAccountUpdate
    ) -> MerchantPayoutAccountResponse:
        """Update a payout account."""
        account = await self.get_payout_account(merchant_id, payout_id)
        if account is None:
            raise ValueError("Payout account not found")
        result = await self._db.execute(
            select(MerchantPayoutAccount).where(
                MerchantPayoutAccount.id == to_uuid(payout_id)
            )
        )
        model = result.scalar_one_or_none()
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(model, key, value)
        await self._db.commit()
        await self._db.refresh(model)
        return self._to_payout_response(model)

    async def delete_payout_account(self, merchant_id: str, payout_id: str) -> None:
        """Delete (soft-delete) a payout account."""
        result = await self._db.execute(
            select(MerchantPayoutAccount).where(
                MerchantPayoutAccount.id == to_uuid(payout_id),
                MerchantPayoutAccount.merchant_id == to_uuid(merchant_id),
            )
        )
        account = result.scalar_one_or_none()
        if account is None:
            raise ValueError("Payout account not found")
        account.is_active = False
        await self._db.commit()
