import sys
from dataclasses import dataclass, field
from os import environ

from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()


@dataclass(frozen=False)
class Config:
    """
    Application configuration and environment variables.
    Uses the stable EchoBot-style pattern for multi-environment compatibility.
    """

    # Core Telegram Credentials
    API_ID: int = field(default_factory=lambda: int(environ.get("API_ID", "0")))
    API_HASH: str = field(default_factory=lambda: environ.get("API_HASH", ""))
    BOT_TOKEN: str = field(default_factory=lambda: environ.get("BOT_TOKEN", ""))

    # Database Configuration
    DATABASE_URL: str = field(default_factory=lambda: environ.get("DATABASE_URL", ""))

    # Ownership and Security
    OWNER_ID: int = field(default_factory=lambda: int(environ.get("OWNER_ID", "0")))

    # Logging and Metadata
    LOG_LEVEL: str = field(default_factory=lambda: environ.get("LOG_LEVEL", "INFO"))
    SCHEDULER_TIMEZONE: str = field(
        default_factory=lambda: environ.get("SCHEDULER_TIMEZONE", "UTC")
    )
    BOT_NAME: str = "lex-tg"
    GITHUB_URL: str = "https://github.com/sudo-py-dev/lex-tg"
    DEV_NAME: str = "sudo-py-dev"
    DEV_URL: str = "https://github.com/sudo-py-dev"
    VERSION: str = "0.0.1"
    SUPPORT_URL: str = "https://www.buymeacoffee.com/chatmagen"
    GITHUB_SPONSORS_URL: str = "https://github.com/sponsors/sudo-py-dev"

    # Feature Flags and Limits
    ENABLE_VIDEO_WATERMARK: bool = field(
        default_factory=lambda: environ.get("ENABLE_VIDEO_WATERMARK", "false").lower() == "true"
    )
    VIDEO_WATERMARK_MAX_SIZE_MB: int = field(
        default_factory=lambda: int(environ.get("VIDEO_WATERMARK_MAX_SIZE_MB", "50"))
    )
    WATERMARK_IMAGE_MAX_SIZE_MB: int = field(
        default_factory=lambda: int(environ.get("WATERMARK_IMAGE_MAX_SIZE_MB", "5"))
    )

    # AI Content Guard (Groq)
    AI_GUARD_MODEL: str = field(
        default_factory=lambda: environ.get("AI_GUARD_MODEL", "llama-3.1-8b-instant")
    )
    AI_GUARD_VISION_MODEL: str = field(
        default_factory=lambda: environ.get(
            "AI_GUARD_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
        )
    )
    AI_GUARD_MAX_IMAGE_SIZE_MB: int = field(
        default_factory=lambda: int(environ.get("AI_GUARD_MAX_IMAGE_SIZE_MB", "10"))
    )

    @property
    def async_db_url(self) -> str:
        """Transforms standard postgresql:// URLs to asyncpg format."""
        url = self.DATABASE_URL
        if not url:
            return ""
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        return url

    def validate(self):
        """Ensures critical variables are present (skipped for CLI tools)."""
        if any(x in sys.argv[0].lower() for x in ["alembic", "pytest"]):
            return

        missing_data = []
        for key in ["API_ID", "API_HASH", "BOT_TOKEN", "DATABASE_URL", "OWNER_ID"]:
            val = environ.get(key)
            if not val or val == "0":
                missing_data.append((key, val))

        if missing_data:
            print("\n" + "=" * 50)
            print("CONFIGURATION ERROR")
            print("=" * 50)
            print("Required variables are missing or invalid:")
            for key, val in missing_data:
                print(f" - {key}: {val or 'NOT FOUND'}")

            print("\nCheck Railway Variables (remove quotes and ensure drafts are deployed).")
            print("=" * 50 + "\n")
            sys.exit(1)


# Instantiate and validate configuration
config = Config()
config.validate()

TECH_STACK = {
    "engine": "[Kurigram](https://github.com/KurimuzonAkuma/kurigram) (Pyrogram Fork)",
    "database": "PostgreSQL (Async)",
    "cache": "Pure Python (Local Snapshot)",
    "framework": "SQLAlchemy 2.0 & Alembic",
    "performance": "Uvloop & Loguru",
}
