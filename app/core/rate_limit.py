# app/core/rate_limit.py
"""
Rate limiting implementation using Redis sliding window counters.
"""

import logging
import time
import uuid

import redis.asyncio as redis
import redis.exceptions
from fastapi import HTTPException, Request
from fastapi.responses import Response

logger = logging.getLogger(__name__)

# Redis connection will be initialized in setup_rate_limiting
redis_client: redis.Redis | None = None

async def init_redis(redis_url: str):
    """Initialize Redis connection."""
    global redis_client
    redis_client = redis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        ssl_cert_reqs=None,
    )

async def sliding_window_allow(
    key: str, 
    limit: int, 
    window_seconds: int
) -> bool:
    """
    Check if a request is allowed under sliding window rate limiting.
    
    Args:
        key: Unique identifier for the rate limit bucket
        limit: Maximum number of requests allowed in the window
        window_seconds: Time window in seconds
        
    Returns:
        True if request is allowed, False otherwise
    """
    if not redis_client:
        # If Redis is not available, allow the request (fail open for safety)
        logger.warning("Redis not available for rate limiting")
        return True
    
    now = time.time()
    pipeline = redis_client.pipeline()
    # Remove old entries outside the window
    pipeline.zremrangebyscore(key, 0, now - window_seconds)
    # Add current request
    pipeline.zadd(key, {str(uuid.uuid4()): now})
    # Get current count
    pipeline.zcard(key)
    # Set expiration
    pipeline.expire(key, window_seconds)

    try:
        results = pipeline.execute()
    except (redis.exceptions.ConnectionError, redis.exceptions.TimeoutError):
        # Redis is unreachable (network down, DNS failure, timeout, etc.)
        # Fail open: allow the request rather than blocking all traffic
        logger.warning("Redis connection failed, rate limiting disabled")
        return True

    current_count = results[2]  # zcard result

    return current_count <= limit

async def rate_limit_middleware(request: Request, call_next):
    """
    FastAPI middleware for rate limiting.
    Applies different limits based on endpoint and user context.
    """
    # Skip rate limiting for health checks and docs
    if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
        return await call_next(request)
    
    # Get client IP
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    
    # Get user ID if available (from auth)
    user_id = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        # In a real implementation, we would decode the token here
        # For now, we'll skip user-specific limits in middleware
        pass
    
    # Define rate limit rules
    limits = [
        # Global per-IP limit: 100 requests/minute
        {
            "key": f"rl:ip:{ip}:{int(time.time() // 60)}",
            "limit": 100,
            "window": 60,
            "description": "Global per-IP limit"
        }
    ]
    
    # Add user-specific limits if user is authenticated
    if user_id:
        limits.append({
            "key": f"rl:user:{user_id}:{int(time.time() // 60)}",
            "limit": 300,
            "window": 60,
            "description": "Per-user limit"
        })
    
    # Special limits for auth endpoints
    if request.url.path.startswith("/auth/"):
        if "login" in request.url.path:
            # Create a combined IP+email hash key for login attempts
            # In practice, we'd extract email from request body
            email_hash = "unknown"  # Placeholder
            limits.append({
                "key": f"rl:login:{ip}:{email_hash}:{int(time.time() // 300)}",  # 5 min window
                "limit": 5,
                "window": 300,
                "description": "Login attempts limit"
            })
        elif "otp" in request.url.path or "password-reset" in request.url.path:
            limits.append({
                "key": f"rl:otp:{user_id or 'unknown'}:{int(time.time() // 900)}",  # 15 min window
                "limit": 3,
                "window": 900,
                "description": "OTP/Password reset limit"
            })
    
    # Checkout specific limit
    if "/orders/checkout" in request.url.path:
        limits.append({
            "key": f"rl:checkout:{user_id or 'unknown'}:{int(time.time() // 60)}",
            "limit": 10,
            "window": 60,
            "description": "Checkout initiation limit"
        })
    
    # Check all limits
    for limit_rule in limits:
        allowed = await sliding_window_allow(
            limit_rule["key"],
            limit_rule["limit"],
            limit_rule["window"]
        )
        
        if not allowed:
            # Calculate retry-after header value
            retry_after = limit_rule["window"]
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit_rule['description']}",
                headers={"Retry-After": str(retry_after)}
            )
    
    response: Response = await call_next(request)
    return response

def setup_rate_limiting(app):
    """Setup rate limiting middleware on the FastAPI app."""
    app.middleware("http")(rate_limit_middleware)