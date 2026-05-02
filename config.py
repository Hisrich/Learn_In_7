"""
config.py - Central configuration module.

Loads all settings from environment variables so the app never
has secrets baked into the codebase. Raises on missing critical values
at startup rather than silently failing at runtime.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    """Raise a clear error if a required env var is missing."""
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            "Check your .env file or deployment environment."
        )
    return value


class Config:
    # ── Flask ──────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "change-me-in-production")
    DEBUG: bool = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    PORT: int = int(os.getenv("PORT", "5000"))

    # ── Database ───────────────────────────────────────────────────────
    # Defaults to SQLite for local dev; swap to PostgreSQL in prod by
    # setting DATABASE_URL=postgresql://user:pass@host/db
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///learning_bot.db"
    )
    # SQLAlchemy needs this flag disabled for SQLite (no-op for Postgres)
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # ── Telegram ───────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
    # Base URL for outbound Telegram calls
    TELEGRAM_API_BASE: str = (
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    )
    # Public HTTPS URL where Telegram will POST updates
    WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")

    # ── Gemini ─────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = _require("GEMINI_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # ── Scheduler ─────────────────────────────────────────────────────
    # How often (seconds) the background job checks for due messages
    SCHEDULER_INTERVAL_SECONDS: int = int(
        os.getenv("SCHEDULER_INTERVAL_SECONDS", "3600")  # every hour
    )

    # ── Retry / Rate-limiting ──────────────────────────────────────────
    MAX_SEND_RETRIES: int = int(os.getenv("MAX_SEND_RETRIES", "3"))
    RETRY_BACKOFF_SECONDS: int = int(os.getenv("RETRY_BACKOFF_SECONDS", "5"))
    # Max Telegram messages per second (global bot limit is ~30/s)
    RATE_LIMIT_PER_SECOND: int = int(os.getenv("RATE_LIMIT_PER_SECOND", "20"))

    # ── Timezone ───────────────────────────────────────────────────────
    # Default tz when a user hasn't specified one
    DEFAULT_TIMEZONE: str = os.getenv("DEFAULT_TIMEZONE", "UTC")


config = Config()
