from sqlalchemy import select

from src.core.context import AppContext
from src.db.models import (
    ChatCleaner,
    ChatNightLock,
    ChatSettings,
    ChatShabbatLock,
    Reminder,
    TimedAction,
)


class SchedulerRepository:
    @staticmethod
    async def get_all_group_settings(ctx: AppContext) -> dict[int, str]:
        """Fetch all active chat IDs and their timezones."""
        async with ctx.db() as session:
            stmt = select(ChatSettings.id, ChatSettings.timezone).where(ChatSettings.isActive)
            result = await session.execute(stmt)
            return {row[0]: row[1] or "UTC" for row in result.all()}

    @staticmethod
    async def get_active_timed_actions(ctx: AppContext, now):
        """Fetch all non-expired timed actions."""
        async with ctx.db() as session:
            stmt = select(TimedAction).where(TimedAction.expiresAt > now)
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_active_reminders(ctx: AppContext):
        """Fetch all active reminders for active chats."""
        async with ctx.db() as session:
            stmt = (
                select(Reminder)
                .join(ChatSettings, Reminder.chatId == ChatSettings.id)
                .where(Reminder.isActive, ChatSettings.isActive)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_active_shabbat_locks(ctx: AppContext):
        """Fetch all enabled Shabbat locks for active chats."""
        async with ctx.db() as session:
            stmt = (
                select(ChatShabbatLock)
                .join(ChatSettings, ChatShabbatLock.chatId == ChatSettings.id)
                .where(ChatShabbatLock.isEnabled, ChatSettings.isActive)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_active_night_locks(ctx: AppContext):
        """Fetch all enabled night locks for active chats."""
        async with ctx.db() as session:
            stmt = (
                select(ChatNightLock)
                .join(ChatSettings, ChatNightLock.chatId == ChatSettings.id)
                .where(ChatNightLock.isEnabled, ChatSettings.isActive)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_active_group_cleaners(ctx: AppContext):
        """Fetch all group cleaners for active chats."""
        async with ctx.db() as session:
            stmt = (
                select(ChatCleaner)
                .join(ChatSettings, ChatCleaner.chatId == ChatSettings.id)
                .where(ChatSettings.isActive)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    @staticmethod
    async def get_group_data(ctx: AppContext, chat_id: int):
        """Fetch all data for a single group for targeted rescheduling."""
        async with ctx.db() as session:
            settings = await session.get(ChatSettings, chat_id)
            if not settings:
                return None, None, None, None, None

            stmt = select(Reminder).where(Reminder.chatId == chat_id, Reminder.isActive)
            reminders = (await session.execute(stmt)).scalars().all()

            stmt = select(ChatNightLock).where(
                ChatNightLock.chatId == chat_id, ChatNightLock.isEnabled
            )
            night_lock = (await session.execute(stmt)).scalars().first()

            stmt = select(ChatShabbatLock).where(
                ChatShabbatLock.chatId == chat_id, ChatShabbatLock.isEnabled
            )
            shabbat_lock = (await session.execute(stmt)).scalars().first()

            stmt = select(ChatCleaner).where(ChatCleaner.chatId == chat_id)
            cleaner = (await session.execute(stmt)).scalars().first()

            return (
                settings.timezone or "UTC",
                reminders,
                night_lock,
                shabbat_lock,
                cleaner,
            )
