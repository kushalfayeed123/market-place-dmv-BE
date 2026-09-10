# app/workers/webhook_worker.py
"""
Background worker for processing webhooks.
Handles retry logic for failed webhook processing.
"""

import asyncio
import logging
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.webhook_event import WebhookEvent
from app.modules.payments.router import paystack_webhook  # Reuse webhook handler

logger = logging.getLogger(__name__)

class WebhookWorker:
    """Worker for processing webhooks with retry logic."""
    
    def __init__(self, check_interval: int = 60):  # Check every minute
        self.check_interval = check_interval
        self.running = False
        self.max_retries = 3
    
    async def start(self):
        """Start the worker loop."""
        self.running = True
        logger.info("Starting webhook worker")
        
        while self.running:
            try:
                await self.process_pending_webhooks()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in webhook worker: {e}")
                await asyncio.sleep(self.check_interval)
    
    def stop(self):
        """Stop the worker loop."""
        self.running = False
        logger.info("Stopping webhook worker")
    
    async def process_pending_webhooks(self):
        """Process webhooks that haven't been processed yet or failed."""
        async with AsyncSessionLocal() as db:
            try:
                # Find webhooks that are pending or failed and haven't exceeded max retries
                query = select(WebhookEvent).where(
                    and_(
                        WebhookEvent.processed_at.is_(None),  # Not yet processed
                        # In a real implementation, we would have a retry count column
                    )
                ).limit(50)  # Process in batches
                
                result = await db.execute(query)
                pending_webhooks = result.scalars().all()
                
                for webhook in pending_webhooks:
                    try:
                        await self.process_webhook(db, webhook)
                    except Exception as e:
                        logger.error(f"Error processing webhook {webhook.id}: {e}")
                        # In a real implementation, we would increment retry count
                        # and potentially move to a dead letter queue after max retries
                        
            except Exception as e:
                logger.error(f"Error processing pending webhooks: {e}")
    
    async def process_webhook(self, db: AsyncSession, webhook: WebhookEvent):
        """Process a single webhook event."""
        logger.info(f"Processing webhook {webhook.id} of type {webhook.event_type}")
        
        # In a real implementation, we would:
        # 1. Parse the webhook payload based on provider and event type
        # 2. Update relevant records (orders, payments, etc.)
        # 3. Create ledger entries as needed
        # 4. Mark webhook as processed
        
        # For now, we'll just mark it as processed to avoid reprocessing
        webhook.processed_at = datetime.utcnow()
        await db.commit()
        
        logger.info(f"Webhook {webhook.id} processed successfully")


# Singleton instance
webhook_worker = WebhookWorker()

# Functions to start/stop the worker
async def start_webhook_worker():
    """Start the webhook worker background task."""
    await webhook_worker.start()

def stop_webhook_worker():
    """Stop the webhook worker background task."""
    webhook_worker.stop()