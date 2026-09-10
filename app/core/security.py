# app/core/security.py
"""
Security utilities for password hashing, JWT creation/verification,
and authentication dependencies.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.db.session import get_db
from app.models.user import User, UserStatus
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Password hashing context using Argon2id
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# OAuth2 scheme for token extraction
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
oauth2_scheme_depends = Depends(oauth2_scheme)
get_db_depends = Depends(get_db)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate Argon2id hash of a password."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token() -> str:
    """Create a cryptographically secure random refresh token."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    """Hash a refresh token for storage (we don't store the raw token)."""
    return pwd_context.hash(token)


def verify_refresh_token(plain_token: str, hashed_token: str) -> bool:
    """Verify a refresh token against its hash."""
    return pwd_context.verify(plain_token, hashed_token)


def to_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """
    Convert a string UUID to a uuid.UUID object.
    
    This is needed because Pydantic schemas use str for UUID fields,
    but SQLAlchemy models with UUID(as_uuid=True) expect uuid.UUID objects.
    
    Args:
        value: A string UUID, uuid.UUID object, or None.
        
    Returns:
        A uuid.UUID object or None if the input was None.
        
    Raises:
        ValueError: If the string is not a valid UUID.
    """
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError) as e:
        raise ValueError(f"Invalid UUID: {value}") from e


async def get_current_user(
    token: str = oauth2_scheme_depends, db: AsyncSession = get_db_depends
) -> User:
    """Dependency to get the current authenticated user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # JWT 'sub' claim may be a dict in some token formats; extract the id value
        if isinstance(user_id, dict):
            user_id = user_id.get("id")
        try:
            target_uuid = to_uuid(user_id)
        except ValueError:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == target_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    return user


# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_current_user_depends = Depends(get_current_user)


async def get_current_active_user(
    current_user: User = get_current_user_depends,
) -> User:
    """Dependency to get the current active user."""
    if current_user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


get_current_active_user_depends = Depends(get_current_active_user)


def require_role(*allowed_roles: str):
    """Dependency factory to require specific roles."""

    def role_dependency(current_user: User = get_current_active_user_depends) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Operation not permitted"
            )
        return current_user

    return role_dependency


def setup_security(app):
    """Setup security middleware and event handlers for OAuth2 bearer token in Swagger UI."""
    
    # Get the OpenAPI schema
    if app.openapi_schema is None:
        app.openapi_schema = app.openapi()
    
    # Add bearer token security scheme
    app.openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})[
        "bearerAuth"
    ] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "Enter your JWT token",
    }
    
    # Apply security globally
    app.openapi_schema.setdefault("security", [{"bearerAuth": []}])
