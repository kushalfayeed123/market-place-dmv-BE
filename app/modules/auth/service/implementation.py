# app/modules/auth/service/implementation.py
"""
Concrete implementation of the auth service.
Handles database operations for authentication using SQLAlchemy.
"""

import secrets
from datetime import datetime, timedelta, timezone

import pyotp
from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    get_password_hash,
    hash_refresh_token,
    to_uuid,
    verify_password,
    verify_refresh_token,
)
from app.models.refresh_token import RefreshToken
from app.models.user import Gender, User, UserRole, UserStatus
from app.modules.auth.service.base import AuthService
from app.schemas.auth import (
    MFASetup,
    MFAVerify,
    PasswordChange,
    PasswordResetRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
    UserUpdate,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class AuthServiceImpl(AuthService):
    """
    Database-backed implementation of AuthService.
    
    This class encapsulates all database operations for authentication,
    using SQLAlchemy's AsyncSession for query execution.
    """

    def __init__(self, db: AsyncSession):
        """
        Initialize the service with a database session.
        
        Args:
            db: The async SQLAlchemy session to use for queries.
        """
        self._db = db

    async def register(self, user_data: UserRegister) -> TokenResponse:
        """
        Register a new user in the database.
        
        Args:
            user_data: The user registration data.
            
        Returns:
            Token response with access and refresh tokens.
            
        Raises:
            ValueError: If email is already registered.
        """
        # Check if user already exists
        result = await self._db.execute(
            select(User).where(User.email == user_data.email)
        )
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise ValueError("Email already registered")

        # Create new user
        hashed_password = get_password_hash(user_data.password)
        new_user = User(
            email=user_data.email,
            phone=user_data.phone,
            password_hash=hashed_password,
            role=UserRole.BUYER if user_data.role == "buyer" else UserRole.MERCHANT_OWNER,
            status=UserStatus.ACTIVE,
            # Profile fields
            first_name=user_data.first_name,
            last_name=user_data.last_name,
            date_of_birth=user_data.date_of_birth,
            preferred_language=user_data.preferred_language,
            gender=Gender(user_data.gender) if user_data.gender else None,
        )

        self._db.add(new_user)
        await self._db.commit()
        await self._db.refresh(new_user)

        # Create tokens
        return await self._create_token_response(new_user)

    async def login(self, login_data: UserLogin) -> TokenResponse:
        """
        Authenticate a user and return tokens.
        
        Args:
            login_data: The user login credentials.
            
        Returns:
            Token response with access and refresh tokens.
            
        Raises:
            ValueError: If credentials are invalid.
        """
        # Find user by email
        result = await self._db.execute(
            select(User).where(User.email == login_data.email)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(login_data.password, user.password_hash):
            raise ValueError("Invalid email or password")

        if user.status != UserStatus.ACTIVE:
            raise ValueError("Account is not active")

        # Create tokens
        return await self._create_token_response(user)

    async def refresh_token(self, refresh_data: RefreshTokenRequest) -> TokenResponse:
        """
        Refresh an access token using a refresh token.
        
        Args:
            refresh_data: The refresh token request.
            
        Returns:
            Token response with new access and refresh tokens.
            
        Raises:
            ValueError: If refresh token is invalid or expired.
        """
        # Fetch all non-revoked refresh tokens
        result = await self._db.execute(
            select(RefreshToken).where(
                                                RefreshToken.revoked_at.is_(None),
            )
        )
        stored_tokens = result.scalars().all()
        
        # Find the matching token using verify_refresh_token
        # Note: We can't compare hashes directly because Argon2 uses random salts
        stored_token = None
        for token in stored_tokens:
            if verify_refresh_token(refresh_data.refresh_token, token.token_hash):
                stored_token = token
                break
        
        if not stored_token:
            raise ValueError("Invalid refresh token")

        # Check if token is expired
        if stored_token.expires_at < datetime.now(timezone.utc):
            raise ValueError("Refresh token expired")

        # Get the user
        result = await self._db.execute(
            select(User).where(User.id == stored_token.user_id)
        )
        user = result.scalar_one_or_none()

        if not user or user.status != UserStatus.ACTIVE:
            raise ValueError("User not found or inactive")

        # Revoke old refresh token
        stored_token.revoked_at = datetime.now(timezone.utc)
        await self._db.commit()

        # Create new tokens
        return await self._create_token_response(user)

    async def setup_mfa(self, user_id: str, mfa_data: MFASetup) -> dict:
        """
        Setup MFA for a user.
        
        Args:
            user_id: The user ID.
            mfa_data: The MFA setup data.
            
        Returns:
            Dictionary with secret and provisioning URI.
        """
        result = await self._db.execute(
            select(User).where(User.id == to_uuid(user_id))
        )
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("User not found")

        # Generate secret if not provided
        if not mfa_data.secret:
            secret = pyotp.random_base32()
        else:
            secret = mfa_data.secret

        user.mfa_secret = secret
        user.mfa_enabled = True
        await self._db.commit()

        # Generate provisioning URI for QR code
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email, issuer_name="Marketplace Platform"
        )

        return {"secret": secret, "provisioning_uri": provisioning_uri}

    async def verify_mfa(self, user_id: str, mfa_data: MFAVerify) -> dict:
        """
        Verify an MFA token.
        
        Args:
            user_id: The user ID.
            mfa_data: The MFA verification data.
            
        Returns:
            Dictionary with verification result.
            
        Raises:
            ValueError: If MFA token is invalid.
        """
        result = await self._db.execute(
            select(User).where(User.id == to_uuid(user_id))
        )
        user = result.scalar_one_or_none()

        if not user or not user.mfa_secret:
            raise ValueError("MFA not set up for this user")

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(mfa_data.token):
            raise ValueError("Invalid MFA token")

        return {"verified": True}

    async def request_password_reset(self, reset_data: PasswordResetRequest) -> dict:
        """
        Request a password reset.
        
        Args:
            reset_data: The password reset request data.
            
        Returns:
            Dictionary with response message.
        """
        result = await self._db.execute(
            select(User).where(User.email == reset_data.email)
        )
        user = result.scalar_one_or_none()

        if user:
            # Generate reset token (in practice, this would be stored and emailed)
            secrets.token_urlsafe(32)

        return {"message": "If the email exists, a reset link has been sent"}

    async def get_user(self, user_id: str) -> UserResponse | None:
        """
        Retrieve a user by their UUID.

        Args:
            user_id: The UUID of the user to retrieve.

        Returns:
            The user response if found, None otherwise.
        """
        try:
            target_uuid = to_uuid(user_id)
        except ValueError:
            return None

        result = await self._db.execute(
            select(User).where(User.id == target_uuid)
        )
        user = result.scalar_one_or_none()

        if user is None:
            return None

        return self._to_user_response(user)

    async def update_user(self, user_id: str, data: UserUpdate) -> UserResponse:
        """
        Partially update a user profile.

        Args:
            user_id: The UUID of the user to update.
            data: The fields to update (all optional; only set values are applied).

        Returns:
            The updated user response.

        Raises:
            ValueError: If the user is not found or the phone is already taken.
        """
        try:
            target_uuid = to_uuid(user_id)
        except ValueError:
            raise ValueError("User not found")

        result = await self._db.execute(
            select(User).where(User.id == target_uuid)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise ValueError("User not found")

        # Build the update dict, only including fields that were explicitly sent
        update_data = data.model_dump(exclude_unset=True)

        # Validate phone uniqueness if it is being changed
        if (
            "phone" in update_data
            and update_data["phone"] is not None
            and update_data["phone"] != user.phone
        ):
            phone_result = await self._db.execute(
                select(User).where(User.phone == update_data["phone"])
            )
            existing = phone_result.scalar_one_or_none()
            if existing:
                raise ValueError("Phone number already in use")

        # Apply gender enum conversion
        if "gender" in update_data and update_data["gender"] is not None:
            update_data["gender"] = Gender(update_data["gender"])

        # Apply updates to the model instance
        for field, value in update_data.items():
            setattr(user, field, value)

        await self._db.commit()
        await self._db.refresh(user)

        return self._to_user_response(user)

    async def change_password(self, user_id: str, data: PasswordChange) -> TokenResponse:
        """
        Change the current user password and issue new tokens.

        Args:
            user_id: The UUID of the user.
            data: The current and new password.

        Returns:
            A new TokenResponse with rotated tokens.

        Raises:
            ValueError: If the current password is incorrect.
        """
        try:
            target_uuid = to_uuid(user_id)
        except ValueError:
            raise ValueError("User not found")

        result = await self._db.execute(
            select(User).where(User.id == target_uuid)
        )
        user = result.scalar_one_or_none()

        if user is None:
            raise ValueError("User not found")

        if not verify_password(data.current_password, user.password_hash):
            raise ValueError("Current password is incorrect")

        user.password_hash = get_password_hash(data.new_password)
        await self._db.commit()
        await self._db.refresh(user)

        return await self._create_token_response(user)

    def _to_user_response(self, user: User) -> UserResponse:
        """Convert a User model instance to a UserResponse schema."""
        return UserResponse(
            id=str(user.id),
            email=user.email,
            phone=user.phone,
            role=user.role.value,
            status=user.status.value,
            first_name=user.first_name,
            last_name=user.last_name,
            date_of_birth=user.date_of_birth,
            avatar_url=user.avatar_url,
            preferred_language=user.preferred_language,
            gender=user.gender.value if user.gender else "unset",
            email_verified_at=user.email_verified_at,
            mfa_enabled=user.mfa_enabled,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    async def _create_token_response(self, user: User) -> TokenResponse:
        """
        Create access and refresh tokens for a user.
        
        Args:
            user: The user model instance.
            
        Returns:
            Token response with tokens and user info.
        """
        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={"sub": str(user.id), "role": user.role.value},
            expires_delta=access_token_expires,
        )
        refresh_token = create_refresh_token()
        hashed_refresh_token = hash_refresh_token(refresh_token)

        # Calculate expiry in Python to avoid MySQL datetime calculation issues
        # func.now() + timedelta can cause "Truncated incorrect DOUBLE value" errors on MySQL
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        
        # Store refresh token
        db_refresh_token = RefreshToken(
            user_id=user.id,
            token_hash=hashed_refresh_token,
            expires_at=expires_at,
        )
        self._db.add(db_refresh_token)
        await self._db.commit()

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            user={
                "id": str(user.id),
                "email": user.email,
                "role": user.role.value,
                "first_name": user.first_name,
                "last_name": user.last_name,
            },
        )
