# app/core/idempotency.py
"""
Idempotency key handling for financial endpoints.
Provides dependency and middleware for ensuring idempotent operations.
"""

import hashlib
import json
import logging

from app.db.session import AsyncSessionLocal, get_db
from app.models.idempotency_key import IdempotencyKey
from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_DB_DEPENDENCY = Depends(get_db)

def hash_request_body(body: bytes) -> str:
    """Create a hash of the request body for idempotency checking."""
    return hashlib.sha256(body).hexdigest()

async def get_idempotency_dependency(
    request: Request,
    db: AsyncSession = _DB_DEPENDENCY
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
            "body": json.loads(idempotency_record.response_body) if idempotency_record.response_body else {}
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
    db: AsyncSession = None,
    status_code: int = 200,
    response_body: dict | None = None,
):
    """
    Call this at the end of a successful request to store the response
    and mark the idempotency key as completed.

    If ``db`` is ``None`` (the common case, since the idempotency dependency
    already closed its own session), a fresh session is opened so the
    record created by ``get_idempotency_dependency`` can be re-queried and
    updated.
    """
    if hasattr(request.state, 'skip_execution') and request.state.skip_execution:
        # Return cached response
        cached = getattr(request.state, 'cached_response', None)
        if cached:
            return cached["status_code"], cached["body"]

    if not hasattr(request.state, 'idempotency_record'):
        # No idempotency tracking needed
        return status_code, response_body or {}

    # Use the provided db session if available, otherwise open a fresh one
    idempotency_key = getattr(request.state, "idempotency_key", None)
    if idempotency_key:
        if db is not None:
            # Use the injected session
            result = await db.execute(
                select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = "completed"
                record.response_status = status_code
                record.response_body = json.dumps(response_body or {}, default=str)
                record.completed_at = func.now()
                await db.commit()
        else:
            # Open a fresh session and re-query the record by key
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
                )
                record = result.scalar_one_or_none()
                if record:
                    record.status = "completed"
                    record.response_status = status_code
                    record.response_body = json.dumps(response_body or {}, default=str)
                    record.completed_at = func.now()
                    await session.commit()

    return status_code, response_body or {}

def setup_idempotency(app):
    """Setup idempotency handling on the FastAPI app."""
    # This would typically involve adding middleware or dependencies
    # For now, we'll rely on explicit dependency usage in endpoints
