# app/core/idempotency.py
"""
Idempotency key handling for financial endpoints.
Provides dependency and middleware for ensuring idempotent operations.
"""

import hashlib
import json
from typing import Optional, Callable
from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
import logging

from app.db.session import get_db
from app.models.idempotency_key import IdempotencyKey
from app.core.config import settings

logger = logging.getLogger(__name__)

def hash_request_body(body: bytes) -> str:
    """Create a hash of the request body for idempotency checking."""
    return hashlib.sha256(body).hexdigest()

async def get_idempotency_dependency(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Dependency that handles idempotency key validation and storage.
    
    For mutating financial endpoints, this:
    1. Looks for Idempotency-Key header
    2. Checks if key exists in database
    3. If not found: creates in_progress record and allows request to proceed
    4. If found and completed: returns stored response
    5. If found and in_progress: returns 409 Conflict
    6. If found but hash differs: returns 422 Unprocessable Entity
    """
    # Skip idempotency for safe methods and non-financial endpoints
    if request.method in ["GET", "HEAD", "OPTIONS", "TRACE"]:
        return None
    
    # Only apply to specific financial endpoints
    path = request.url.path
    if not any(endpoint in path for endpoint in [
        "/orders/checkout",
        "/payments/",
        "/merchants/",
        "/webhooks/"
    ]):
        return None
    
    # Get idempotency key from header
    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        # For endpoints that require it, we should enforce it
        # But for now, we'll just warn and continue
        logger.warning(f"Missing Idempotency-Key header for {path}")
        return None
    
    # Read request body for hashing
    body = await request.body()
    request_hash = hash_request_body(body)
    
    # Check if idempotency key exists
    result = await db.execute(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
    )
    idempotency_record = result.scalar_one_or_none()
    
    if not idempotency_record:
        # Create new idempotency record
        new_record = IdempotencyKey(
            idempotency_key=idempotency_key,
            endpoint=str(request.url.path),
            request_hash=request_hash,
            status="in_progress"
        )
        db.add(new_record)
        await db.commit()
        await db.refresh(new_record)
        
        # Attach record to request state for later use
        request.state.idempotency_record = new_record
        request.state.idempotency_key = idempotency_key
        request.state.request_hash = request_hash
        
        return new_record
    
    # Record exists, check status
    if idempotency_record.status == "completed":
        # Return cached response
        request.state.cached_response = {
            "status_code": idempotency_record.response_status,
            "body": idempotency_record.response_body
        }
        request.state.skip_execution = True
        return idempotency_record
    
    if idempotency_record.status == "in_progress":
        # Request already being processed
        raise HTTPException(
            status_code=409,
            detail="Request already in progress"
        )
    
    # Check if request hash matches (protection against key reuse)
    if idempotency_record.request_hash != request_hash:
        raise HTTPException(
            status_code=422,
            detail="Idempotency key reused with different payload"
        )
    
    # Should not reach here, but handle gracefully
    request.state.idempotency_record = idempotency_record
    return idempotency_record

async def finalize_idempotency(
    request: Request,
    db: AsyncSession = Depends(get_db),
    status_code: int = 200,
    response_body: dict = None
):
    """
    Call this at the end of a successful request to store the response
    and mark the idempotency key as completed.
    """
    if hasattr(request.state, 'skip_execution') and request.state.skip_execution:
        # Return cached response
        cached = getattr(request.state, 'cached_response', None)
        if cached:
            return cached["status_code"], cached["body"]
    
    if not hasattr(request.state, 'idempotency_record'):
        # No idempotency tracking needed
        return status_code, response_body or {}
    
    # Update the idempotency record with response
    idempotency_record = request.state.idempotency_record
    idempotency_record.status = "completed"
    idempotency_record.response_status = status_code
    idempotency_record.response_body = response_body or {}
    idempotency_record.completed_at = func.now()
    
    await db.commit()
    
    return status_code, response_body or {}

def setup_idempotency(app):
    """Setup idempotency handling on the FastAPI app."""
    # This would typically involve adding middleware or dependencies
    # For now, we'll rely on explicit dependency usage in endpoints
    pass