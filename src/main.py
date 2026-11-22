import asyncio
import contextlib
import os
import socket
import sqlite3
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger
from pyrogram.errors import (
    AccessTokenExpired,
    AccessTokenInvalid,
    AuthKeyDuplicated,
    AuthKeyInvalid,
    AuthKeyUnregistered,
    FloodWait,
    Unauthorized,
)

from src.config import config
from src.core.context import AppContext, set_context
from src.core.plugin import autodiscover, get_plugins
from src.db.client import AsyncSessionLocal, disconnect_db
from src.db.engine import create_db_tables
from src.utils.local_cache import get_cache
from src.utils.logger import setup_logger


async def wait_for_db(host: str = "db", port: int = 5432, timeout: int = 30) -> bool:
    """Wait for the database to be reachable."""
    logger.info(f"⏳ Waiting for database at {host}:{port}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                logger.info("✅ Database is reachable.")
                return True
        except (TimeoutError, ConnectionRefusedError):
            await asyncio.sleep(1)
    logger.error("❌ Database connection timed out.")
    return False


async def update_heartbeat() -> None:
    """Updates a heartbeat file to signal health to Docker."""
    try:
        hb_path = Path("data/heartbeat")
        hb_path.write_text(str(int(time.time())))
    except Exception as e:
        logger.error(f"Failed to update heartbeat: {e}")


def run() -> None:
    """Entry point for the application."""
    setup_logger()

    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("postgresql"):
        try:
            parts = db_url.split("@")[-1].split("/")[0].split(":")
            host = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 5432
            asyncio.run(wait_for_db(host, port))
        except Exception:
            asyncio.run(wait_for_db())

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())


async def main() -> None:
    from src.core.bot import bot

    # Initialize database tables
    logger.info("🔄 Initializing database...")
    try:
        await create_db_tables()
        logger.info("✅ Database initialized successfully.")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")

    logger.info(f"Starting {config.BOT_NAME}...")

    cache = get_cache()
    await cache.load_snapshot()

    scheduler = AsyncIOScheduler(
        timezone=ZoneInfo(config.SCHEDULER_TIMEZONE),
        job_defaults={
            "misfire_grace_time": 60,
            "coalesce": True,
        }
    )
    scheduler.start()

    scheduler.add_job(cache.save_snapshot, "interval", minutes=4, id="cache_snapshot")
    scheduler.add_job(cache.cleanup_expired, "interval", minutes=5, id="cache_cleanup")
    scheduler.add_job(update_heartbeat, "interval", minutes=1, id="heartbeat")

    ctx = AppContext(db=AsyncSessionLocal, cache=cache, scheduler=scheduler)
    set_context(ctx)

    autodiscover("src.plugins")
    for plugin in get_plugins():
        try:
            await plugin.setup(bot, ctx)
            logger.debug(f"Plugin initialized: {plugin.name}")
        except Exception as e:
            logger.error(f"Failed to initialize plugin {plugin.name}: {e}")

    try:
        await bot.start()
        config.BOT_NAME = bot.me.first_name
        logger.info(f"{config.BOT_NAME} is running!")
        await asyncio.Event().wait()
    except sqlite3.OperationalError as e:
        if "database is locked" in str(e):
            logger.error(
                f"🚨 {config.BOT_NAME} failed to start: The database is locked. "
                "This usually means another instance of the bot is already running. "
                "Please make sure to close other sessions before starting a new one."
            )
        else:
            logger.error(f"Database error: {e}")
    except AuthKeyDuplicated:
        logger.critical(
            f"🚨 {config.BOT_NAME} startup failed: Auth key is duplicated. Make sure only one instance is using the session file."
        )
    except (AccessTokenInvalid, AccessTokenExpired):
        logger.critical(
            f"🚨 {config.BOT_NAME} startup failed: Bot token is invalid or expired. Check your .env file."
        )
    except FloodWait as e:
        logger.critical(
            f"🚨 {config.BOT_NAME} is rate-limited by Telegram (Flood Wait). "
            f"Please wait {e.value} seconds before attempting to start the bot again."
        )
    except (AuthKeyInvalid, AuthKeyUnregistered, Unauthorized) as e:
        logger.critical(
            f"🚨 {config.BOT_NAME} startup failed: Unauthorized ({e}). Try deleting the session file and logging in again."
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning(f"{config.BOT_NAME} is shutting down...")
    except Exception as e:
        logger.exception(f"{config.BOT_NAME} execution failed: {e}")
    finally:
        logger.debug("Synchronizing shutdown...")
        for plugin in reversed(get_plugins()):
            try:
                await asyncio.wait_for(plugin.teardown(), timeout=5.0)
            except Exception as e:
                logger.error(f"Failed to teardown plugin {plugin.name}: {e}")

        scheduler.shutdown(wait=False)
        await cache.save_snapshot()
        await disconnect_db()

        if bot.is_connected:
            try:
                logger.debug("Closing Telegram connection...")
                await bot.stop()
            except Exception as e:
                logger.warning(f"Error during Telegram connection closure: {e}")

        logger.info(f"{config.BOT_NAME} shutdown complete.")


if __name__ == "__main__":
    run()
