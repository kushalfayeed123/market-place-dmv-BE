# app/tests/test_auth.py
"""
Tests for authentication endpoints.
"""

import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_register_user(client: AsyncClient):
    """Test user registration."""
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "password": "securepassword123",
            "role": "buyer",
            "first_name": "Test",
            "last_name": "User",
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["role"] == "buyer"


@pytest.mark.asyncio
async def test_login_user(client: AsyncClient):
    """Test user login."""
    # First register a user
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test2@example.com",
            "password": "securepassword123",
            "role": "buyer",
            "first_name": "Test",
            "last_name": "Two",
        }
    )

    # Then login using form data (OAuth2PasswordRequestForm)
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "test2@example.com",
            "password": "securepassword123"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_register_duplicate_email(client: AsyncClient):
    """Test registering with duplicate email."""
    # Register first user
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test3@example.com",
            "password": "securepassword123",
            "role": "buyer",
            "first_name": "Test",
            "last_name": "Three",
        }
    )

    # Try to register again with same email
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test3@example.com",
            "password": "differentpassword456",
            "role": "buyer",
            "first_name": "Test",
            "last_name": "Three",
        }
    )
    assert response.status_code == 400
    assert "already registered" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient):
    """Test login with invalid credentials."""
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": "nonexistent@example.com",
            "password": "wrongpassword"
        }
    )
    assert response.status_code == 401
