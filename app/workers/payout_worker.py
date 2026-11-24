# app/workers/payout_worker.py
"""
Background worker for automatic payout release.
Releases held funds after delivery confirmation and dispute window period.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

import uuid

from app.db.session import AsyncSessionLocal
from app.models.ledger_entry import LedgerDirection, LedgerEntry, LedgerEntryType
from app.models.fulfillment import Fulfillment, FulfillmentStatus
from app.models.order import Order
from app.models.payout import Payout

logger = logging.getLogger(__name__)

class PayoutWorker:
    """Worker for automatically releasing payout holds."""
    
    def __init__(self, check_interval: int = 300):  # Check every 5 minutes
        self.check_interval = check_interval
        self.running = False
    
    async def start(self):
        """Start the worker loop."""
        self.running = True
        logger.info("Starting payout worker")
        
        while self.running:
            try:
                await self.process_eligible_payouts()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in payout worker: {e}")
                await asyncio.sleep(self.check_interval)  # Continue despite errors
    
    def stop(self):
        """Stop the worker loop."""
        self.running = False
        logger.info("Stopping payout worker")
    
    async def process_eligible_payouts(self):
        """Process payouts eligible for release."""
        async with AsyncSessionLocal() as db:
            try:
                # Find fulfillments that have been delivered and whose dispute window has passed
                query = select(Fulfillment).where(
                    and_(
                        Fulfillment.status.in_([FulfillmentStatus.DELIVERED.value, FulfillmentStatus.DELIVERED_DIGITAL.value]),
                        Fulfillment.dispute_window_ends <= datetime.utcnow(),
                        # Check if there's a payout_hold entry that hasn't been released yet
                        # This would join with ledger entries in practice
                    )
                )
                
                result = await db.execute(query)
                eligible_fulfillments = result.scalars().all()
                
                for fulfillment in eligible_fulfillments:
                    try:
                        await self.release_payout_for_fulfillment(db, fulfillment)
                    except Exception as e:
                        logger.error(f"Error releasing payout for fulfillment {fulfillment.id}: {e}")
                        
            except Exception as e:
                logger.error(f"Error processing eligible payouts: {e}")
    
    async def release_payout_for_fulfillment(self, db: AsyncSession, fulfillment: Fulfillment):
            """Release payout hold for a specific fulfillment.

            1. Find the unreleased payout_hold entry for this order + merchant.
            2. Create a payout_release ledger entry that supersedes it.
            3. Update the Payout status to 'paid' if one exists.
            4. Update fulfillment status to 'delivered' if it isn't already.
            """
            order = await self._db.get(Order, fulfillment.order_id)
            if not order:
                return

            # Find the unreleased payout_hold entry for this order + merchant
            hold_res = await db.execute(
                select(LedgerEntry).where(
                    LedgerEntry.order_id == order.id,
                    LedgerEntry.merchant_id == fulfillment.merchant_id,
                    LedgerEntry.entry_type == LedgerEntryType.PAYOUT_HOLD.value,
                    LedgerEntry.id.not_in(
                        select(LedgerEntry.supersedes_entry_id).where(
                            LedgerEntry.supersedes_entry_id.isnot(None)
                        )
                    ),
                )
            )
            holds = hold_res.scalars().all()

            # Create payout_release entry for each unreleased hold
            for hold in holds:
                db.add(
                    LedgerEntry(
                        entry_group_id=uuid.uuid4(),
                        account_type="merchant_wallet",
                        merchant_id=fulfillment.merchant_id,
                        direction=LedgerDirection.CREDIT.value,
                        entry_type=LedgerEntryType.PAYOUT_RELEASE.value,
                        amount=hold.amount,
                        currency=hold.currency,
                        order_id=order.id,
                        supersedes_entry_id=hold.id,
                        created_by="system",
                    )
                )

            # Mark the Payout as paid if it exists and is still requested/processing
            if order.payout_id:
                payout_res = await db.execute(
                    select(Payout).where(Payout.id == order.payout_id)
                )
                payout = payout_res.scalar_one_or_none()
                if payout and payout.status in ("requested", "processing"):
                    payout.status = "paid"
                    payout.paid_at = datetime.utcnow()
                    db.add(payout)

            # Update fulfillment status to delivered
            if fulfillment.status not in (FulfillmentStatus.DELIVERED.value, FulfillmentStatus.DELIVERED_DIGITAL.value):
                fulfillment.status = FulfillmentStatus.DELIVERED.value
                fulfillment.delivered_at = datetime.utcnow()

            await db.commit()


# Singleton instance
payout_worker = PayoutWorker()

# Function to start the worker (would be called from main.py lifespan event)
async def start_payout_worker():
    """Start the payout worker background task."""
    await payout_worker.start()

# Function to stop the worker
def stop_payout_worker():
    """Stop the payout worker background task."""
    payout_worker.stop()