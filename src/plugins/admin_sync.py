from pyrogram import Client, ContinuePropagation, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import ChatMemberUpdated, Message

from src.core.bot import bot
from src.core.context import get_context
from src.db.repositories.admins import remove_admin, upsert_admin
from src.utils.admin_cache import invalidate_cache
from src.utils.chat_types import normalize_chat_type

_REGISTERED_CHATS = set()


async def ensure_chat_identity(ctx, chat):
    """Ensure the chat type and title/activation are correctly persisted in the database."""
    if chat.id in _REGISTERED_CHATS:
        return

    from src.db.repositories.chats import get_chat_settings, update_settings

    settings = await get_chat_settings(ctx, chat.id)
    chat_type = normalize_chat_type(chat.type).name.lower()

    linked_id = getattr(chat, "linked_chat_id", None)
    if (
        settings.chatType != chat_type
        or settings.title != chat.title
        or settings.linkedChatId != linked_id
        or not settings.isActive
    ):
        await update_settings(
            ctx,
            chat.id,
            chatType=chat_type,
            title=chat.title,
            linkedChatId=linked_id,
            isActive=True,
        )

    _REGISTERED_CHATS.add(chat.id)


@bot.on_message(filters.group | filters.channel, group=-90)
async def auto_register_chat(client: Client, message: Message):
    """Automatically register chat identity on any incoming message."""
    await ensure_chat_identity(get_context(), message.chat)
    raise ContinuePropagation


@bot.on_chat_member_updated(group=-90)
async def on_chat_member_updated(client: Client, update: ChatMemberUpdated):
    """
    Real-time synchronization of group administrators and bot identity.
    Tracks promotions, demotions, departures, and chat meta updates.
    """
    if update.chat.type == ChatType.PRIVATE:
        return

    ctx = get_context()
    chat_id = update.chat.id
    user_id = (
        update.new_chat_member.user.id if update.new_chat_member else update.old_chat_member.user.id
    )

    new_status = update.new_chat_member.status if update.new_chat_member else None
    old_status = update.old_chat_member.status if update.old_chat_member else None

    is_now_admin = new_status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    was_previously_admin = old_status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}

    if user_id == client.me.id:
        from src.db.repositories.chats import get_chat_settings, update_settings
        from src.utils.admin_cache import sync_admins_from_telegram

        # Ensure Identity & Activation
        settings = await get_chat_settings(ctx, chat_id)
        is_active = new_status in {
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
            ChatMemberStatus.MEMBER,
        }

        # Update isActive status
        if settings.isActive != is_active:
            await update_settings(ctx, chat_id, isActive=is_active)

        # Trigger full admin sync if bot is now an admin (newly added or promoted)
        if is_now_admin:
            import asyncio

            # Run in background to not block the update handler
            asyncio.create_task(sync_admins_from_telegram(client, chat_id, force=True))

        # Update botPrivileges in ChatSettings
        if update.new_chat_member and update.new_chat_member.privileges:
            import json

            m = update.new_chat_member
            privs = {
                attr: getattr(m.privileges, attr, False)
                for attr in dir(m.privileges)
                if attr.startswith("can_")
            }
            await update_settings(ctx, chat_id, botPrivileges=json.dumps(privs))

            # Update cache for bot_privs
            from src.utils.local_cache import get_cache

            await get_cache().setex(f"bot_privs:{chat_id}", 3600, privs)
        elif not is_active:
            await update_settings(ctx, chat_id, botPrivileges=None)

        # Also send dashboard if promoted
        if not was_previously_admin and is_now_admin and update.from_user:
            import contextlib

            from src.plugins.admin_panel.handlers.commands import send_admin_dashboard

            with contextlib.suppress(Exception):
                await send_admin_dashboard(
                    client, update.from_user.id, chat_id, text_key="panel.promotion_notify"
                )

    if is_now_admin:
        m = update.new_chat_member
        privs = None
        if m.privileges:
            privs = {
                attr: getattr(m.privileges, attr, False)
                for attr in dir(m.privileges)
                if attr.startswith("can_")
            }
        await upsert_admin(
            ctx,
            chat_id,
            user_id,
            new_status.name.lower(),
            m.user.first_name,
            m.user.username,
            privs,
        )
        await invalidate_cache(chat_id, user_id)

        # Auto-send admin panel to newly promoted administrators
        if not was_previously_admin and user_id != client.me.id:
            import contextlib

            from src.plugins.admin_panel.handlers.commands import send_admin_dashboard

            with contextlib.suppress(Exception):
                await send_admin_dashboard(
                    client, user_id, chat_id, text_key="panel.promotion_notify"
                )

    elif was_previously_admin and not is_now_admin:
        # Demoted, Left, or Banned
        await remove_admin(ctx, chat_id, user_id)
        await invalidate_cache(chat_id, user_id)
    raise ContinuePropagation
