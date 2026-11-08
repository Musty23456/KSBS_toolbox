"""
Centralized application settings, loaded from environment variables / .env.

No secrets are hardcoded here — everything comes from the environment so the
same code works across local development, CI, and production.
"""

import re
from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # ---------------------------------------------------------
    # Application
    # ---------------------------------------------------------

    APP_NAME: str = "KBS Toolbox API"
    APP_ENV: str = "development"

    # ---------------------------------------------------------
    # Database
    # ---------------------------------------------------------

    DATABASE_URL: str = "sqlite:///./kbs_toolbox.db"

    # ---------------------------------------------------------
    # JWT Authentication
    # ---------------------------------------------------------

    JWT_SECRET_KEY: str = "insecure-dev-secret-change-me"
    JWT_ALGORITHM: str = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    CORS_ALLOWED_ORIGINS: str = (
        "http://localhost:5173,http://localhost:3000"
    )

    # ---------------------------------------------------------
    # Rate Limiting
    # ---------------------------------------------------------

    RATE_LIMIT_PER_MINUTE: int = 60

    # ---------------------------------------------------------
    # Media
    # ---------------------------------------------------------

    MEDIA_ROOT: str = "./media"

    # ---------------------------------------------------------
    # Demo / Seed Data
    # ---------------------------------------------------------

    SEED_DEMO_DATA: bool = True

    DEMO_ADMIN_EMAIL: str = "admin@kbstoolbox.app"
    DEMO_ADMIN_PASSWORD: str = "ChangeMe123!"

    # ---------------------------------------------------------
    # Resend Email Configuration
    # ---------------------------------------------------------
    #
    # Password-reset emails are sent through the Resend HTTPS API.
    #
    # IMPORTANT:
    # Never put the real RESEND_API_KEY directly in this file.
    # Set it as an environment variable in Render.
    #

    RESEND_API_KEY: str = ""

    RESEND_FROM_EMAIL: str = ""

    # ---------------------------------------------------------
    # Web Application
    # ---------------------------------------------------------

    WEB_APP_URL: str = "http://localhost:5173"

    # ---------------------------------------------------------
    # Password Reset
    # ---------------------------------------------------------

    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30

    # ---------------------------------------------------------
    # AI Integration (Google Gemini)
    # ---------------------------------------------------------
    #
    # AI is OFF by default. The API key is only ever read on the server and is
    # never returned by any endpoint or written to logs.
    #
    # IMPORTANT:
    # Never put a real GEMINI_API_KEY in this file or in version control.
    # Set it in backend/.env (git-ignored) or as a host environment variable.
    #

    AI_ENABLED: bool = False
    AI_PROVIDER: str = "gemini"

    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Seconds to wait for one provider call, and how many times to retry
    # transient failures (network error, timeout, 5xx). Quota and
    # invalid-key errors are never retried.
    AI_REQUEST_TIMEOUT: int = 30
    AI_MAX_RETRIES: int = 2

    # Per-user limit for AI endpoints (on top of the global per-IP limit).
    AI_RATE_LIMIT_PER_MINUTE: int = 10

    # Largest request body (bytes) AI endpoints accept, and the longest
    # prompt (characters) the AI service will forward to a provider.
    AI_MAX_REQUEST_BYTES: int = 16384
    AI_MAX_PROMPT_CHARS: int = 8000

    # Phase 2 - AI questionnaire generator. A full questionnaire is a much
    # bigger job than the Phase 1 test call, so it gets its own limits.
    AI_GENERATION_TIMEOUT: int = 90  # seconds per provider call
    AI_GENERATION_MAX_REQUEST_BYTES: int = 65536
    AI_GENERATION_MAX_PROMPT_CHARS: int = 30000
    AI_GENERATION_MAX_OUTPUT_TOKENS: int = 32768
    AI_GENERATION_MAX_QUESTIONS: int = 100

    # Phase 3 - AI questionnaire editor. The request carries the whole questionnaire in the builder.
    AI_EDIT_MAX_REQUEST_BYTES: int = 262144

    @field_validator("AI_PROVIDER")
    @classmethod
    def _validate_ai_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in {"gemini"}:
            raise ValueError("AI_PROVIDER must be one of: gemini")
        return value

    @field_validator("GEMINI_API_KEY")
    @classmethod
    def _strip_api_key(cls, value: str) -> str:
        return value.strip()

    @field_validator("GEMINI_MODEL")
    @classmethod
    def _validate_gemini_model(cls, value: str) -> str:
                value = value.strip().strip("\"'").strip()
        if value.lower().startswith("models/"):
            value = value[len("models/"):]
        return value

    @field_validator("AI_REQUEST_TIMEOUT")
    @classmethod
    def _validate_ai_timeout(cls, value: int) -> int:
        if not 1 <= value <= 120:
            raise ValueError("AI_REQUEST_TIMEOUT must be between 1 and 120 seconds")
        return value

    @field_validator("AI_MAX_RETRIES")
    @classmethod
    def _validate_ai_retries(cls, value: int) -> int:
        if not 0 <= value <= 5:
            raise ValueError("AI_MAX_RETRIES must be between 0 and 5")
        return value

    @field_validator("AI_RATE_LIMIT_PER_MINUTE")
    @classmethod
    def _validate_ai_rate_limit(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AI_RATE_LIMIT_PER_MINUTE must be at least 1")
        return value

    @field_validator("AI_MAX_REQUEST_BYTES", "AI_MAX_PROMPT_CHARS")
    @classmethod
    def _validate_ai_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AI size limits must be positive")
        return value

    @field_validator("AI_GENERATION_TIMEOUT")
    @classmethod
    def _validate_ai_generation_timeout(cls, value: int) -> int:
        if not 1 <= value <= 300:
            raise ValueError("AI_GENERATION_TIMEOUT must be between 1 and 300 seconds")
        return value

    @field_validator(
        "AI_GENERATION_MAX_REQUEST_BYTES",
        "AI_GENERATION_MAX_PROMPT_CHARS",
        "AI_GENERATION_MAX_OUTPUT_TOKENS",
        "AI_GENERATION_MAX_QUESTIONS",
        "AI_EDIT_MAX_REQUEST_BYTES",
    )
    @classmethod
    def _validate_ai_generation_limits(cls, value: int) -> int:
        if value < 1:
            raise ValueError("AI generation limits must be positive")
        return value

    # ---------------------------------------------------------
    # Helper Properties
    # ---------------------------------------------------------

    @property
    def cors_origins_list(self) -> List[str]:
        """
        Convert the comma-separated CORS_ALLOWED_ORIGINS string
        into a clean list of origins.
        """

        return [
            origin.strip()
            for origin in self.CORS_ALLOWED_ORIGINS.split(",")
            if origin.strip()
        ]

    @property
    def is_production(self) -> bool:
        """
        Return True when the application is running in production.
        """

        return self.APP_ENV.lower() == "production"


# -------------------------------------------------------------
# Cached Settings
# -------------------------------------------------------------

@lru_cache
def get_settings() -> Settings:
    """
    Return the application settings.

    lru_cache ensures the Settings object is created only once
    during the application's lifetime.
    """

    return Settings()
