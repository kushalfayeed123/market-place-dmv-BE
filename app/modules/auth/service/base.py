# app/modules/auth/service/base.py
"""
Abstract base class for auth service.
Defines the interface that all auth service implementations must follow.
"""

from abc import ABC, abstractmethod

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


class AuthService(ABC):
    """
    Abstract interface for authentication operations.
    
    This class defines the contract for any auth service implementation,
    allowing the routing layer to remain decoupled from database specifics.
    """

    @abstractmethod
    async def register(self, user_data: UserRegister) -> TokenResponse:
        """
        Register a new user.
        
        Args:
            user_data: The user registration data.
            
        Returns:
            Token response with access and refresh tokens.
            
        Raises:
            ValueError: If email is already registered.
        """
        ...

    @abstractmethod
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
    @abstractmethod
    async def logout(self, user_id: str) -> dict:
        """
        Log the user out by revoking all of their active refresh tokens.

        Args:
            user_id: The UUID of the user to log out.

        Returns:
            A dictionary with a confirmation message.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def get_user(self, user_id: str) -> UserResponse | None:
        """
        Retrieve a user by their UUID.
        
        Args:
            user_id: The UUID of the user to retrieve.
            
        Returns:
            The user response if found, None otherwise.
        """
        ...

    @abstractmethod
    async def update_user(self, user_id: str, data: UserUpdate) -> UserResponse:
        """
        Partially update a user's profile.
        
        Args:
            user_id: The UUID of the user to update.
            data: The fields to update (all optional).
            
        Returns:
            The updated user response.
            
        Raises:
            ValueError: If the user is not found or the phone is already taken.
        """
        ...

    @abstractmethod
    async def change_password(self, user_id: str, data: PasswordChange) -> TokenResponse:
        """
        Change the current user's password and issue new tokens.
        
        Args:
            user_id: The UUID of the user.
            data: The current and new password.
            
        Returns:
            A new TokenResponse with rotated tokens.
            
        Raises:
            ValueError: If the current password is incorrect.
        """
        ...

    @abstractmethod
    async def setup_mfa(self, user_id: str, mfa_data: MFASetup) -> dict:
        """
        Setup MFA for a user.
        
        Args:
            user_id: The user ID.
            mfa_data: The MFA setup data.
            
        Returns:
            Dictionary with secret and provisioning URI.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def request_password_reset(self, reset_data: PasswordResetRequest) -> dict:
        """
        Request a password reset.
        
        Args:
            reset_data: The password reset request data.
            
        Returns:
            Dictionary with response message.
        """
        ...
