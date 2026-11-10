"""Local Cache and DB-backed admin management. Avoids redundant API calls."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from enum import Enum

from loguru import logger
from pyrogram import Client, enums
from pyrogram.types import ChatPermissions

from src.core.constants import CacheKeys
from src.core.context import get_context
from src.db.models.chats import ChatAdmin
from src.db.repositories.admins import (
    get_admin_from_db,
    get_admins_for_chat,
    replace_chat_admins,
)
from src.utils.local_cache import get_cache

_TTL = 3600  # 1 hour for local cache

# To avoid multiple concurrent API calls for the same chat
fetching_semaphore = asyncio.Semaphore(5)
sync_locks = defaultdict(asyncio.Lock)


class Permission(Enum):
    CAN_BAN = "can_restrict_members"
    CAN_RESTRICT = "can_restrict_members"
    CAN_PROMOTE = "can_promote_members"
    CAN_DELETE = "can_delete_messages"
    CAN_PIN = "can_pin_messages"
    CAN_INVITE = "can_invite_users"
    CAN_CHANGE_INFO = "can_change_info"
    CAN_MANAGE_VIDEO_CHATS = "can_manage_video_chats"
    CAN_POST = "can_post_messages"
    CAN_EDIT = "can_edit_messages"
    CAN_MANAGE_TOPICS = "can_manage_topics"


RESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_change_info=False,
    can_invite_users=False,
    can_pin_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
)

UNRESTRICTED_PERMISSIONS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_add_web_page_previews=True,
    can_change_info=True,
    can_invite_users=True,
    can_pin_messages=True,
)


async def sync_admins_from_telegram(client: Client, chat_id: int, force: bool = False) -> set[int]:
    """
    Fetch full admin list from Telegram, update DB and Local Cache.
    This is the primary way to re-synchronize a chat's administration state.
    """
    if chat_id is None:
        return set()
    if chat_id > 0:
        return {chat_id}

    cache = get_cache()
    cooldown_key = f"admin_sync_cooldown:{chat_id}"

    if not force and await cache.exists(cooldown_key):
        logger.debug(f"Admin sync for {chat_id} suppressed (cooldown active)")
        # Return what we have in DB/Cache currently to avoid re-triggering sync
        ctx = get_context()
        db_admins = await get_admins_for_chat(ctx, chat_id)
        if db_admins:
            return {a.userId for a in db_admins}
        return set()

    async with fetching_semaphore, sync_locks[chat_id]:
        ctx = get_context()
        try:
            admin_ids = set()
            # Set cooldown early to prevent rapid concurrent hits
            await cache.setex(cooldown_key, 600, True)  # 10 minutes

            # Fetch the entire list before changing persisted membership.
            admins = []
            details = {}

            async for m in client.get_chat_members(
                chat_id, filter=enums.ChatMembersFilter.ADMINISTRATORS
            ):
                if not m.user:
                    continue

                admin_ids.add(m.user.id)
                status = m.status.name.lower()
                privs = None
                if m.privileges:
                    privs = {
                        attr: getattr(m.privileges, attr, False)
                        for attr in dir(m.privileges)
                        if attr.startswith("can_")
                    }

                admins.append(
                    ChatAdmin(
                        chatId=chat_id,
                        userId=m.user.id,
                        status=status,
                        firstName=m.user.first_name,
                        username=m.user.username,
                        privileges=json.dumps(privs) if privs else None,
                    )
                )
                details[m.user.id] = "owner" if status == "owner" else privs or {}

            previous_admins = await get_admins_for_chat(ctx, chat_id)
            await replace_chat_admins(ctx, chat_id, admins)

            # Remove privileges for demoted/departed admins as well as refreshing members.
            for previous in previous_admins:
                await cache.delete(f"admin_detail:{chat_id}:{previous.userId}")
            await cache.delete(f"bot_privs:{chat_id}")
            for user_id, detail in details.items():
                await cache.setex(f"admin_detail:{chat_id}:{user_id}", _TTL, detail)

            from src.db.repositories.chats import update_chat_setting

            bot_detail = details.get(client.me.id)
            bot_privileges = bot_detail if isinstance(bot_detail, dict) else {}
            await update_chat_setting(ctx, chat_id, "botPrivileges", json.dumps(bot_privileges))
            if bot_detail is not None:
                await cache.setex(f"bot_privs:{chat_id}", _TTL, bot_detail)

            # Update global list cache
            await cache.set(CacheKeys.admins(chat_id), json.dumps(list(admin_ids)), ttl=_TTL)
            logger.debug(f"Admin cache/DB refreshed for chat {chat_id}: {len(admin_ids)} admins")
            return admin_ids
        except Exception as e:
            logger.warning(f"Failed to fetch admins for chat {chat_id}: {e}")
            # If it failed, maybe don't hold the cooldown too long?
            await cache.delete(cooldown_key)
            return set()


async def _ensure_synced(client: Client, chat_id: int) -> None:
    """Helper to ensure admins are synced if cache is older than 24h."""
    from src.db.repositories.chats import get_chat_settings

    settings = await get_chat_settings(get_context(), chat_id)
    if not settings.lastAdminsUpdate or (
        settings.lastAdminsUpdate.replace(tzinfo=None)
        < datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    ):
        await sync_admins_from_telegram(client, chat_id, force=True)


async def is_admin(client: Client, chat_id: int | None, user_id: int | None) -> bool:
    """Check if user is admin using 3-tier logic: Cache -> DB -> API."""
    if not chat_id or not user_id:
        return False
    if chat_id > 0:
        return chat_id == user_id

    await _ensure_synced(client, chat_id)

    # 1. Tier: Local Cache
    r = get_cache()
    cached_list = await r.get(CacheKeys.admins(chat_id))
    if cached_list and user_id in json.loads(cached_list):
        return True

    # 2. Tier: Database
    db_admin = await get_admin_from_db(get_context(), chat_id, user_id)
    if db_admin:
        privs = json.loads(db_admin.privileges) if db_admin.privileges else {}
        await r.setex(
            f"admin_detail:{chat_id}:{user_id}",
            _TTL,
            "owner" if db_admin.status == "owner" else privs,
        )
        return True

    # 3. Tier: API Fallback
    return user_id in await sync_admins_from_telegram(client, chat_id)


async def is_owner(client: Client, chat_id: int | None, user_id: int | None) -> bool:
    """Check if user is the owner of the chat."""
    if not chat_id or not user_id:
        return False
    if chat_id > 0:
        return chat_id == user_id

    await _ensure_synced(client, chat_id)

    cache = get_cache()
    cached = await cache.get(f"admin_detail:{chat_id}:{user_id}")
    if cached == "owner":
        return True

    db_admin = await get_admin_from_db(get_context(), chat_id, user_id)
    return bool(db_admin and db_admin.status == "owner")


async def get_chat_admins(client: Client, chat_id: int) -> list[int]:
    """Get the full list of admin IDs for a chat, following the 3-tier logic."""
    if chat_id is None:
        return []
    if chat_id > 0:
        return [chat_id]

    # 1. Tier: Local Cache
    r = get_cache()
    cached = await r.get(CacheKeys.admins(chat_id))
    if cached:
        try:
            return json.loads(cached)
        except json.JSONDecodeError:
            pass

    # 2. Tier: Database
    from src.db.repositories.admins import get_admins_for_chat

    ctx = get_context()
    db_admins = await get_admins_for_chat(ctx, chat_id)
    if db_admins:
        ids = [a.userId for a in db_admins]
        # Repopulate detailed cache for each while we are at it
        for a in db_admins:
            privs = json.loads(a.privileges) if a.privileges else {}
            await r.setex(
                f"admin_detail:{chat_id}:{a.userId}",
                _TTL,
                "owner" if a.status == "owner" else privs,
            )
        # Update set cache
        await r.set(CacheKeys.admins(chat_id), json.dumps(ids), ttl=_TTL)
        return ids

    # 3. Tier: API Fallback
    return list(await sync_admins_from_telegram(client, chat_id))


async def invalidate_cache(chat_id: int | None, user_id: int | None = None) -> None:
    """Invalidate local cache keys. DB remains until next sync."""
    if chat_id is None:
        return
    r = get_cache()
    await r.delete(CacheKeys.admins(chat_id))
    if user_id:
        await r.delete(f"admin_detail:{chat_id}:{user_id}")
    logger.debug(f"Admin cache invalidated for chat {chat_id}")


async def force_refresh(client: Client, chat_id: int | None) -> set[int]:
    """Force re-fetch from Telegram and update DB/Cache."""
    if chat_id is None:
        return set()
    await invalidate_cache(chat_id)
    return await sync_admins_from_telegram(client, chat_id, force=True)


async def check_user_permission(
    client: Client, chat_id: int | None, user_id: int, permission: Permission
) -> bool:
    """Check if a specific user has a privilege using 3-tier: Cache -> DB -> API."""
    if chat_id is None:
        return False
    if chat_id > 0:
        return chat_id == user_id

    # 1. Tier: Local Cache
    cache = get_cache()
    cache_key = f"admin_detail:{chat_id}:{user_id}"

    await _ensure_synced(client, chat_id)

    cached = await cache.get(cache_key)

    if cached == "owner":
        return True
    if isinstance(cached, dict):
        return cached.get(permission.value, False)
    if cached is False:
        return False

    # 2. Tier: Database
    ctx = get_context()
    db_admin = await get_admin_from_db(ctx, chat_id, user_id)
    if db_admin:
        if db_admin.status == "owner":
            await cache.setex(cache_key, _TTL, "owner")
            return True

        privs = {}
        if db_admin.privileges:
            try:
                privs = json.loads(db_admin.privileges)
            except json.JSONDecodeError:
                privs = {}

        await cache.setex(cache_key, _TTL, privs)
        return privs.get(permission.value, False)

    # 3. Tier: API Fallback
    # Note: sync_admins_from_telegram will populate both DB and Cache for ALL admins
    await sync_admins_from_telegram(client, chat_id)

    # Check cache again after refresh
    cached = await cache.get(cache_key)
    if cached == "owner":
        return True
    if isinstance(cached, dict):
        return cached.get(permission.value, False)

    return False


async def has_permission(client: Client, chat_id: int | None, permission: Permission) -> bool:
    """Check if the BOT has a specific permission in a chat. Optimized via ChatSettings."""
    if chat_id is None:
        return False

    # 1. Check specialized bot permission cache
    cache = get_cache()
    bot_cache_key = f"bot_privs:{chat_id}"
    cached_privs = await cache.get(bot_cache_key)

    if cached_privs == "owner":
        return True
    if isinstance(cached_privs, dict):
        return cached_privs.get(permission.value, False)

    # 2. Check Database (ChatSettings first for efficiency)
    from src.db.repositories.chats import get_chat_settings

    ctx = get_context()
    settings = await get_chat_settings(ctx, chat_id)
    if settings and settings.botPrivileges:
        try:
            privs = json.loads(settings.botPrivileges)
            await cache.setex(bot_cache_key, _TTL, privs)
            return privs.get(permission.value, False)
        except json.JSONDecodeError:
            pass

    # 3. Fallback to full check (which will trigger sync if needed)
    return await check_user_permission(client, chat_id, client.me.id, permission)
