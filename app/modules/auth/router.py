# app/modules/auth/router.py
"""
Authentication router handling user registration, login, refresh, and MFA.
Communicates with the service layer via the AuthService abstraction.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.idempotency import finalize_idempotency, get_idempotency_dependency
from app.core.security import get_current_active_user
from app.modules.auth.service.base import AuthService
from app.modules.auth.service.dependency import get_auth_service
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

router = APIRouter()

# Module-level dependency singletons (avoids B008 function calls in argument defaults)
get_idempotency_depends = Depends(get_idempotency_dependency)
get_current_active_user_depends = Depends(get_current_active_user)
get_auth_service_depends = Depends(get_auth_service)
oauth2_form_depends = Depends(OAuth2PasswordRequestForm)


@router.post("/register", response_model=TokenResponse)
async def register(
    request: Request,
    user_data: UserRegister,
    idempotency: dict = get_idempotency_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Register a new user (buyer or merchant owner).
    Rate limited and requires idempotency key.
    """
    try:
        response_data = await service.register(user_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_201_CREATED, response_body=response_data.model_dump()
    )
    return response_data


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = oauth2_form_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Authenticate a user and return tokens.
    Rate limited and requires idempotency key.
    """
    login_data = UserLogin(email=form_data.username, password=form_data.password)

    try:
        response_data = await service.login(login_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data.model_dump()
    )
    return response_data


@router.post("/logout")
async def logout(
    request: Request,
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Log the current user out by revoking their active refresh tokens.
    Requires authentication.
    """
    return await service.logout(str(current_user.id))


@router.post("/refresh", response_model=TokenResponse)
@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    refresh_data: RefreshTokenRequest,
    service: AuthService = get_auth_service_depends,
):
    """
    Refresh an access token using a refresh token.
    Rate limited and requires idempotency key.
    """
    try:
        response_data = await service.refresh_token(refresh_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data.model_dump()
    )
    return response_data


@router.post("/mfa/setup")
async def setup_mfa(
    request: Request,
    mfa_data: MFASetup,
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """
    Setup MFA for the current user.
    Requires authentication and idempotency key.
    """
    # Only allow certain roles to set up MFA
    if current_user.role.value not in ["merchant_owner", "platform_admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only merchant owners and platform admins can set up MFA",
        )

    try:
        response_data = await service.setup_mfa(str(current_user.id), mfa_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data
    )
    return response_data


@router.post("/mfa/verify")
async def verify_mfa(
    request: Request,
    mfa_data: MFAVerify,
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """
    Verify MFA token for the current user.
    Used for login challenge and step-up verification.
    """
    try:
        response_data = await service.verify_mfa(str(current_user.id), mfa_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data
    )
    return response_data


@router.post("/password-reset/request")
async def request_password_reset(
    request: Request,
    reset_data: PasswordResetRequest,
    service: AuthService = get_auth_service_depends,
    idempotency: dict = get_idempotency_depends,
):
    """
    Request a password reset token.
    Rate limited and requires idempotency key.
    """
    response_data = await service.request_password_reset(reset_data)

    await finalize_idempotency(
        request, None, status_code=status.HTTP_200_OK, response_body=response_data
    )
    return response_data


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Get the current authenticated user's profile.
    Used by the agent to address the user appropriately.
    """
    user = await service.get_user(str(current_user.id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return user


@router.put("/me", response_model=UserResponse)
async def update_current_user_profile(
    update_data: UserUpdate,
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Update the current authenticated user's profile.
    """
    try:
        user = await service.update_user(str(current_user.id), update_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return user


@router.put("/me/password")
async def change_current_user_password(
    password_data: PasswordChange,
    current_user: dict = get_current_active_user_depends,
    service: AuthService = get_auth_service_depends,
):
    """
    Change the current user's password.
    """
    try:
        token_response = await service.change_password(str(current_user.id), password_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    return token_response


# Include the router in the main app
def get_router():
    return router
