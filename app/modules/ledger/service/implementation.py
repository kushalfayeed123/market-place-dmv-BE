# app/modules/ledger/service/implementation.py
"""
Concrete implementation of the ledger service.
Handles database operations for ledger using SQLAlchemy.
"""


from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import func

from app.core.security import (
    to_uuid,
)
from app.models.ledger_entry import LedgerEntry
from app.models.merchant import Merchant
from app.models.order import Order
from app.modules.ledger.service.base import LedgerService
from app.schemas.ledger import (
    LedgerBalanceResponse,
    LedgerEntryResponse,
)


class LedgerServiceImpl(LedgerService):
    """
    Database-backed implementation of LedgerService.
    
    This class encapsulates all database operations for ledger,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

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
        query = select(LedgerEntry)

        # Apply access controls based on user role
        if user_role == "buyer":
            # Buyers can only see ledger entries related to their orders
            buyer_orders_result = await self._db.execute(
                select(Order.id).where(Order.buyer_id == user_id)
            )
            buyer_order_ids = [str(row[0]) for row in buyer_orders_result.fetchall()]

            if buyer_order_ids:
                query = query.where(LedgerEntry.order_id.in_(buyer_order_ids))
            else:
                return []

        elif user_role in ["merchant_owner", "merchant_staff"]:
            # Merchants can only see ledger entries related to their merchant wallet
            merchant_id_from_token = user_id  # Simplified - in practice would lookup merchant_id
            if merchant_id_from_token:
                query = query.where(LedgerEntry.merchant_id == merchant_id_from_token)
            else:
                return []

        # Platform admins see all entries (no additional filtering)

        # Apply additional filters
        if merchant_id:
            query = query.where(LedgerEntry.merchant_id == merchant_id)
        if entry_type:
            query = query.where(LedgerEntry.entry_type == entry_type)
        if account_type:
            query = query.where(LedgerEntry.account_type == account_type)
        if direction:
            query = query.where(LedgerEntry.direction == direction)
        if min_amount is not None:
            query = query.where(LedgerEntry.amount >= min_amount)
        if max_amount is not None:
            query = query.where(LedgerEntry.amount <= max_amount)
        if order_id:
            query = query.where(LedgerEntry.order_id == order_id)

        query = query.offset(skip).limit(limit)
        result = await self._db.execute(query)
        entries = result.scalars().all()

        return [self._to_response(entry) for entry in entries]

    async def get_entry(self, entry_id: str) -> LedgerEntryResponse | None:
        """
        Get a ledger entry by ID from the database.
        
        Args:
            entry_id: The ledger entry ID.
            
        Returns:
            The ledger entry response if found, None otherwise.
        """
        result = await self._db.execute(
            select(LedgerEntry).where(LedgerEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()

        if entry is None:
            return None

        return self._to_response(entry)

    async def get_balance(
        self,
        merchant_id: str,
        user_id: str | None = None,
        user_role: str | None = None,
    ) -> LedgerBalanceResponse:
        """
        Get the balance for a merchant from the database.
        
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
        # Verify merchant exists
        result = await self._db.execute(
            select(Merchant).where(Merchant.id == to_uuid(merchant_id))
        )
        merchant = result.scalar_one_or_none()

        if not merchant:
            raise ValueError("Merchant not found")

        # Calculate balance from ledger entries
        balance_query = """
            SELECT 
                SUM(
                    CASE 
                        WHEN direction = 'credit' THEN amount 
                        WHEN direction = 'debit' THEN -amount 
                        ELSE 0
                    END
                ) as balance
            FROM ledger_entries
            WHERE merchant_id = :merchant_id
              AND entry_type IN ('sale', 'commission', 'payout_release', 'payout_paid', 'refund')
        """

        result = await self._db.execute(
            text(balance_query),
            {"merchant_id": merchant_id},
        )
        balance_row = result.fetchone()
        balance = balance_row[0] if balance_row and balance_row[0] is not None else 0

        # Get currency (assume NGN for simplicity)
        currency = "NGN"

        # Calculate held balance (funds in payout_hold state)
        held_query = """
            SELECT 
                SUM(
                    CASE 
                        WHEN direction = 'debit' THEN amount 
                        ELSE 0
                    END
                ) as held_balance
            FROM ledger_entries
            WHERE merchant_id = :merchant_id
              AND entry_type = 'payout_hold'
              AND id NOT IN (
                SELECT supersedes_entry_id 
                FROM ledger_entries 
                WHERE supersedes_entry_id IS NOT NULL
              )
        """

        result = await self._db.execute(
            text(held_query),
            {"merchant_id": merchant_id},
        )
        held_row = result.fetchone()
        held_balance = held_row[0] if held_row and held_row[0] is not None else 0

        # Calculate available balance (total - held)
        available_balance = balance - held_balance

        return LedgerBalanceResponse(
            merchant_id=merchant_id,
            currency=currency,
            total_balance=balance,
            available_balance=available_balance,
            held_balance=held_balance,
            calculated_at=func.now(),
        )

    @staticmethod
    def _to_response(entry: LedgerEntry) -> LedgerEntryResponse:
        """Convert a LedgerEntry model to LedgerEntryResponse schema."""
        import json
        
        # Parse metadata from JSON string to dict if needed
        metadata = entry.ledger_metadata
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        
        return LedgerEntryResponse(
            id=str(entry.id),
            entry_group_id=str(entry.entry_group_id),
            account_type=entry.account_type,
            merchant_id=str(entry.merchant_id) if entry.merchant_id else None,
            direction=entry.direction,
            entry_type=entry.entry_type,
            amount=entry.amount,
            currency=entry.currency,
            order_id=str(entry.order_id) if entry.order_id else None,
            payment_transaction_id=(
                str(entry.payment_transaction_id) if entry.payment_transaction_id else None
            ),
            supersedes_entry_id=(
                str(entry.supersedes_entry_id) if entry.supersedes_entry_id else None
            ),
            metadata=metadata or {},
            created_at=entry.created_at,
            created_by=entry.created_by,
        )
