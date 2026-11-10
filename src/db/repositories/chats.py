import asyncio
import contextlib
import json
from typing import Any

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import BadRequest, FloodWait, Forbidden, RPCError
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError

from src.core.context import AppContext
from src.db.models import ChatAdmin, ChatSettings
from src.utils.chat_types import normalize_chat_type
from src.utils.i18n import at


async def _get_or_create_settings(ctx: AppContext, chat_id: int, session) -> ChatSettings:
    settings = await session.get(ChatSettings, chat_id)
    if not settings:
        try:
            async with session.begin_nested():
                settings = ChatSettings(id=chat_id)
                session.add(settings)
            await session.commit()
        except IntegrityError:
            await session.rollback()
            settings = await session.get(ChatSettings, chat_id)
    return settings


async def get_chat_settings(ctx: AppContext, chat_id: int) -> ChatSettings:
    """Get chat settings, creating them if they don't exist."""
    async with ctx.db() as session:
        return await _get_or_create_settings(ctx, chat_id, session)


async def toggle_setting(ctx: AppContext, chat_id: int, field: str) -> bool:
    """Toggle a boolean setting field."""
    async with ctx.db() as session:
        s = await _get_or_create_settings(ctx, chat_id, session)
        val = not getattr(s, field)
        setattr(s, field, val)
        session.add(s)
        await session.commit()
        return val


async def update_chat_setting(ctx: AppContext, chat_id: int, field: str, value: Any) -> None:
    """Update a specific setting field with a value."""
    async with ctx.db() as session:
        s = await _get_or_create_settings(ctx, chat_id, session)
        setattr(s, field, value)
        session.add(s)
        await session.commit()


async def update_settings(ctx: AppContext, chat_id: int, **kwargs) -> ChatSettings:
    """Update multiple fields in ChatSettings."""
    async with ctx.db() as session:
        settings = await session.get(ChatSettings, chat_id)
        if not settings:
            settings = ChatSettings(id=chat_id, **kwargs)
            session.add(settings)
        else:
            for key, value in kwargs.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
            session.add(settings)

        await session.commit()
        await session.refresh(settings)
        return settings


async def update_chat_title(ctx: AppContext, chat_id: int, title: str) -> None:
    """Update the persistent chat title in the database."""
    async with ctx.db() as session:
        settings = await session.get(ChatSettings, chat_id)
        if not settings:
            settings = ChatSettings(id=chat_id)

        settings.title = title
        session.add(settings)
        await session.commit()


async def toggle_service_type(ctx: AppContext, chat_id: int, service_type: str) -> None:
    """Toggle a service message type in the cleanServiceTypes JSON array."""
    async with ctx.db() as session:
        s = await _get_or_create_settings(ctx, chat_id, session)
        try:
            ts = json.loads(s.cleanServiceTypes or "[]")
        except (json.JSONDecodeError, TypeError):
            ts = []

        if service_type in ts:
            ts.remove(service_type)
        else:
            ts.append(service_type)

        s.cleanServiceTypes = json.dumps(ts)
        session.add(s)
        await session.commit()


async def get_user_admin_chats(
    ctx: AppContext,
    client: Client,
    user_id: int,
    chat_type: ChatType | list[ChatType] | None = None,
    check_admin: bool = False,
) -> list[tuple[int, str]]:
    """Get active chats where user is admin, optionally filtered by type.

    Args:
        check_admin: If True, verify admin status via API (slow, causes rate limits).
                     If False, return all matching chats from DB (fast, for menu listing).
                     Admin check should be done when selecting a specific chat, not when listing.
    """
    async with ctx.db() as session:
        stmt = (
            select(ChatSettings)
            .join(ChatAdmin, ChatSettings.id == ChatAdmin.chatId)
            .where(
                and_(
                    ChatSettings.isActive,
                    ChatSettings.id < 0,
                    ChatAdmin.userId == user_id,
                )
            )
        )

        if chat_type:
            types = (
                [ct.name.lower() for ct in chat_type]
                if isinstance(chat_type, list)
                else [chat_type.name.lower()]
            )
            stmt = stmt.where(ChatSettings.chatType.in_(types))
        res = await session.execute(stmt)
        all_s = res.scalars().all()

    results, sem = [], asyncio.Semaphore(10)

    async def check(s: ChatSettings):
        async with sem:
            cid = int(s.id)
            if s.title:
                return results.append((cid, s.title))
            try:
                chat = await client.get_chat(cid)
                title = chat.title or await at(user_id, "panel.unknown_chat", id=cid)
                results.append((cid, title))
                await update_chat_title(ctx, cid, title)
                if normalize_chat_type(chat.type).name.lower() != s.chatType:
                    await update_chat_setting(
                        ctx, cid, "chatType", normalize_chat_type(chat.type).name.lower()
                    )
            except (BadRequest, Forbidden, RPCError, FloodWait):
                results.append((cid, await at(user_id, "panel.unknown_chat", id=cid)))

    await asyncio.gather(*(check(s) for s in all_s))
    return results


async def get_chat_info(ctx: AppContext, chat_id: int) -> tuple[ChatType, str]:
    """Resolve ChatType and title for a chat, with fallbacks."""
    settings = await get_chat_settings(ctx, chat_id)
    chat_type = ChatType.SUPERGROUP
    title = settings.title or f"Chat {chat_id}"

    if settings and settings.chatType:
        with contextlib.suppress(KeyError, AttributeError):
            chat_type = normalize_chat_type(ChatType[settings.chatType.upper()])

    from src.core.bot import bot

    try:
        chat = await bot.get_chat(chat_id)
        chat_type = normalize_chat_type(chat.type)
        title = chat.title or chat.first_name or title
    except (BadRequest, Forbidden, RPCError):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        with contextlib.suppress(RPCError):
            chat = await bot.get_chat(chat_id)
            chat_type = normalize_chat_type(chat.type)
    if settings.chatType != chat_type.name.lower() or settings.title != title:
        await update_settings(ctx, chat_id, chatType=chat_type.name.lower(), title=title)
    return chat_type, title


async def resolve_chat_type(ctx: AppContext, chat_id: int) -> ChatType:
    """Resolve ChatType from DB with Pyrogram fallback."""
    chat_type, _ = await get_chat_info(ctx, chat_id)
    return chat_type


async def set_chat_active_status(ctx: AppContext, chat_id: int, is_active: bool) -> None:
    """Set the active status of a chat."""
    async with ctx.db() as session:
        settings = await session.get(ChatSettings, chat_id)
        if not settings:
            try:
                async with session.begin_nested():
                    settings = ChatSettings(id=chat_id, isActive=is_active)
                    session.add(settings)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                settings = await session.get(ChatSettings, chat_id)
                if settings:
                    settings.isActive = is_active
                    session.add(settings)
                    await session.commit()
        else:
            settings.isActive = is_active
            session.add(settings)
            await session.commit()


async def get_all_active_chats(ctx: AppContext) -> list[ChatSettings]:
    """Retrieve all chats marked as active in the database."""
    async with ctx.db() as session:
        stmt = select(ChatSettings).where(ChatSettings.isActive)
        res = await session.execute(stmt)
        return list(res.scalars().all())
