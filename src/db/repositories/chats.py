import asyncio
import contextlib
import json
from typing import Any

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import RPCError
from sqlalchemy import Boolean, and_, func, select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.context import AppContext
from src.db.models import ChatAdmin, ChatSettings
from src.utils.chat_types import normalize_chat_type
from src.utils.i18n import at
from src.utils.message_rules import invalidate_rules

_RULE_FIELDS = {"blacklistAction", "blacklistScanButtons"}


def _settings_column(field: str):
    column = ChatSettings.__table__.columns.get(field)
    if column is None or column.primary_key:
        raise ValueError(f"Unknown or immutable chat setting: {field}")
    return column


async def _ensure_settings(session: AsyncSession, chat_id: int) -> None:
    dialect = session.get_bind().dialect.name
    insert = sqlite_insert if dialect == "sqlite" else postgres_insert
    await session.execute(
        insert(ChatSettings).values(id=chat_id).on_conflict_do_nothing(index_elements=["id"])
    )


async def get_chat_settings(ctx: AppContext, chat_id: int) -> ChatSettings:
    """Get chat settings, creating them if they don't exist."""
    async with ctx.db() as session:
        settings = await session.get(ChatSettings, chat_id)
        if settings is None:
            await _ensure_settings(session, chat_id)
            await session.commit()
            settings = await session.get(ChatSettings, chat_id)
        return settings


async def toggle_setting(ctx: AppContext, chat_id: int, field: str) -> bool:
    """Atomically toggle a boolean setting field."""
    column = _settings_column(field)
    if not isinstance(column.type, Boolean):
        raise ValueError(f"Chat setting is not boolean: {field}")
    async with ctx.db() as session:
        await _ensure_settings(session, chat_id)
        value = await session.scalar(
            update(ChatSettings)
            .where(ChatSettings.id == chat_id)
            .values({field: ~func.coalesce(column, False)})
            .returning(column)
        )
        await session.commit()
    if field in _RULE_FIELDS:
        await invalidate_rules("settings", chat_id)
    return bool(value)


async def update_chat_setting(ctx: AppContext, chat_id: int, field: str, value: Any) -> None:
    """Update a specific setting field with a value."""
    await update_settings(ctx, chat_id, **{field: value})


async def update_settings(ctx: AppContext, chat_id: int, **kwargs) -> ChatSettings:
    """Update multiple fields in one transaction."""
    for field in kwargs:
        _settings_column(field)
    async with ctx.db() as session:
        await _ensure_settings(session, chat_id)
        if kwargs:
            await session.execute(
                update(ChatSettings).where(ChatSettings.id == chat_id).values(**kwargs)
            )
        await session.commit()
        settings = await session.get(ChatSettings, chat_id)
    if _RULE_FIELDS.intersection(kwargs):
        await invalidate_rules("settings", chat_id)
    return settings


async def update_chat_title(ctx: AppContext, chat_id: int, title: str) -> None:
    await update_chat_setting(ctx, chat_id, "title", title)


async def toggle_service_type(ctx: AppContext, chat_id: int, service_type: str) -> None:
    """Toggle a service message type in the stored JSON array."""
    async with ctx.db() as session:
        await _ensure_settings(session, chat_id)
        if session.get_bind().dialect.name == "postgresql":
            s = await session.get(ChatSettings, chat_id, with_for_update=True)
        else:
            # The insert above acquires SQLite's write lock for this transaction.
            s = await session.get(ChatSettings, chat_id)
        try:
            values = json.loads(s.cleanServiceTypes or "[]")
        except (json.JSONDecodeError, TypeError):
            values = []
        if not isinstance(values, list):
            values = []
        if service_type in values:
            values.remove(service_type)
        else:
            values.append(service_type)
        s.cleanServiceTypes = json.dumps(values)
        await session.commit()


async def get_user_admin_chats(
    ctx: AppContext,
    client: Client,
    user_id: int,
    chat_type: ChatType | list[ChatType] | None = None,
) -> list[tuple[int, str]]:
    """Get the active chats recorded for an admin."""
    chats, _, _ = await get_user_admin_chat_page(ctx, client, user_id, chat_type)
    return chats


async def get_user_admin_chat_page(
    ctx: AppContext,
    client: Client,
    user_id: int,
    chat_type: ChatType | list[ChatType] | None = None,
    *,
    page: int = 0,
    page_size: int | None = None,
) -> tuple[list[tuple[int, str]], int, int]:
    """Return a stable slice, total count, and the clamped page index."""
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
        # Hydrating a missing title must not move the chat to a different page.
        stmt = stmt.order_by(ChatSettings.id)
        if page_size is not None:
            total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
            page = min(max(0, page), max(0, (total - 1) // page_size))
            stmt = stmt.offset(page * page_size).limit(page_size)
        res = await session.execute(stmt)
        all_s = res.scalars().all()
        if page_size is None:
            total = len(all_s)
            page = 0

    sem = asyncio.Semaphore(10)

    async def check(s: ChatSettings):
        async with sem:
            cid = int(s.id)
            if s.title:
                return cid, s.title
            try:
                chat = await client.get_chat(cid)
                title = chat.title or await at(user_id, "panel.unknown_chat", id=cid)
                await update_chat_title(ctx, cid, title)
                if normalize_chat_type(chat.type).name.lower() != s.chatType:
                    await update_chat_setting(
                        ctx, cid, "chatType", normalize_chat_type(chat.type).name.lower()
                    )
                return cid, title
            except RPCError:
                return cid, await at(user_id, "panel.unknown_chat", id=cid)

    results = await asyncio.gather(*(check(s) for s in all_s))
    return results, total, page


async def get_chat_info(
    ctx: AppContext, chat_id: int, *, refresh: bool = True
) -> tuple[ChatType, str]:
    """Resolve ChatType and title for a chat, with fallbacks."""
    settings = await get_chat_settings(ctx, chat_id)
    chat_type = ChatType.SUPERGROUP
    title = settings.title or f"Chat {chat_id}"

    if settings and settings.chatType:
        with contextlib.suppress(KeyError, AttributeError):
            chat_type = normalize_chat_type(ChatType[settings.chatType.upper()])
            if not refresh and settings.title:
                return chat_type, title

    from src.core.bot import bot

    try:
        chat = await bot.get_chat(chat_id)
        chat_type = normalize_chat_type(chat.type)
        title = chat.title or chat.first_name or title
    except RPCError:
        return chat_type, title
    if settings.chatType != chat_type.name.lower() or settings.title != title:
        await update_settings(ctx, chat_id, chatType=chat_type.name.lower(), title=title)
    return chat_type, title


async def resolve_chat_type(ctx: AppContext, chat_id: int) -> ChatType:
    """Resolve ChatType from DB with Pyrogram fallback."""
    chat_type, _ = await get_chat_info(ctx, chat_id)
    return chat_type


async def set_chat_active_status(ctx: AppContext, chat_id: int, is_active: bool) -> None:
    """Set the active status of a chat."""
    await update_chat_setting(ctx, chat_id, "isActive", is_active)


async def get_all_active_chats(ctx: AppContext) -> list[ChatSettings]:
    """Retrieve all chats marked as active in the database."""
    async with ctx.db() as session:
        stmt = select(ChatSettings).where(ChatSettings.isActive)
        res = await session.execute(stmt)
        return list(res.scalars().all())
