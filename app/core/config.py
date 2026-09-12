# app/core/config.py
"""
Application configuration using pydantic-settings.
Loads settings from environment variables and .env files.
"""

import secrets
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
        env_file_encoding="utf-8",
    )

    # Application
    PROJECT_NAME: str = "Marketplace"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Security
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    JWT_SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production", env="JWT_SECRET"
    )
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database
    DATABASE_URL: str = Field(..., env="DATABASE_URL")
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    DB_ECHO: bool = False

    # Redis
    REDIS_URL: str = Field(..., env="REDIS_URL")
    REDIS_PASSWORD: str = Field(default="redis", env="REDIS_PASSWORD")

    # CORS
    BACKEND_CORS_ORIGINS: list[str] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: str | list[str]) -> list[str] | str:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Paystack
    PAYSTACK_SECRET_KEY: str = Field(..., env="PAYSTACK_SECRET_KEY")
    PAYSTACK_PUBLIC_KEY: str = Field(..., env="PAYSTACK_PUBLIC_KEY")

    # Cloudflare R2
    R2_BUCKET: str = Field(..., env="R2_BUCKET")
    R2_ACCESS_KEY_ID: str = Field(..., env="R2_ACCESS_KEY_ID")
    R2_SECRET_ACCESS_KEY: str = Field(..., env="R2_SECRET_ACCESS_KEY")

    # Feature Flags
    KYC_ENFORCEMENT_ENABLED: bool = Field(False, env="KYC_ENFORCEMENT_ENABLED")

    # Support notifications (delivered by app/workers/support_notify_worker.py)
    SUPPORT_WEBHOOK_URL: str = Field("", env="SUPPORT_WEBHOOK_URL")       # empty = webhook disabled
    SUPPORT_WEBHOOK_SECRET: str = Field("", env="SUPPORT_WEBHOOK_SECRET")  # HMAC-SHA256 signing key
    SUPPORT_SMTP_HOST: str = Field("", env="SUPPORT_SMTP_HOST")           # empty = email disabled
    SUPPORT_SMTP_PORT: int = Field(587, env="SUPPORT_SMTP_PORT")
    SUPPORT_SMTP_USER: str = Field("", env="SUPPORT_SMTP_USER")
    SUPPORT_SMTP_PASSWORD: str = Field("", env="SUPPORT_SMTP_PASSWORD")
    SUPPORT_EMAIL_FROM: str = Field("", env="SUPPORT_EMAIL_FROM")
    SUPPORT_EMAIL_TO: str = Field("", env="SUPPORT_EMAIL_TO")             # comma-separated pickup mailbox(es)

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == "development"

    @property
    def is_staging(self) -> bool:
        return self.ENVIRONMENT == "staging"

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def async_database_url(self) -> str:
        """Ensure the database URL uses an async driver."""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith(("mysql://", "mariadb://")):
            url = url.replace("mysql://", "mysql+asyncmy://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
