import json

from loguru import logger
from pyrogram import Client, ContinuePropagation, filters, raw, utils
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import ChannelPrivate, RPCError, UserNotParticipant
from pyrogram.types import Chat, ChatMember, ChatMemberUpdated, Message

from src.core.bot import bot
from src.core.context import get_context
from src.db.repositories.admins import remove_admin, upsert_admin
from src.utils.admin_cache import invalidate_cache, sync_locks
from src.utils.chat_types import normalize_chat_type
from src.utils.local_cache import get_cache

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


async def refresh_bot_permissions(client: Client, chat, member: ChatMember) -> None:
    """Apply self-membership changes even when no channel post is received."""
    from src.db.repositories.chats import update_settings

    ctx = get_context()
    chat_id = chat.id
    is_admin = member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    is_active = member.status in {
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
        ChatMemberStatus.MEMBER,
    }
    privileges = (
        {
            attr: bool(getattr(member.privileges, attr, False))
            for attr in dir(member.privileges)
            if attr.startswith("can_")
        }
        if is_admin and member.privileges
        else {}
    )
    detail = "owner" if member.status == ChatMemberStatus.OWNER else privileges

    # Full admin snapshots share this lock so they cannot interleave DB/cache writes.
    async with sync_locks[chat_id]:
        await update_settings(
            ctx,
            chat_id,
            chatType=normalize_chat_type(chat.type).name.lower(),
            title=chat.title,
            isActive=is_active,
            botPrivileges=json.dumps(privileges),
        )
        if is_admin:
            await upsert_admin(
                ctx,
                chat_id,
                client.me.id,
                member.status.name.lower(),
                client.me.first_name,
                client.me.username,
                privileges,
            )
        else:
            await remove_admin(ctx, chat_id, client.me.id)
        await invalidate_cache(chat_id, client.me.id)
        cache = get_cache()
        await cache.setex(f"bot_privs:{chat_id}", 3600, detail)
        await cache.setex(
            f"admin_detail:{chat_id}:{client.me.id}", 3600, detail if is_admin else False
        )
    _REGISTERED_CHATS.discard(chat_id)


@bot.on_raw_update(group=-89)
async def on_channel_permissions_changed(client: Client, update, users, chats):
    """Telegram also signals changes to the bot's channel rights via UpdateChannel."""
    if not isinstance(update, raw.types.UpdateChannel):
        raise ContinuePropagation
    chat_id = utils.get_channel_id(update.channel_id)
    try:
        chat = await client.get_chat(chat_id)
        try:
            member = await client.get_chat_member(chat_id, client.me.id)
        except UserNotParticipant:
            member = ChatMember(user=client.me, status=ChatMemberStatus.LEFT)
        await refresh_bot_permissions(client, chat, member)
    except ChannelPrivate:
        from src.db.repositories.chats import get_chat_settings

        settings = await get_chat_settings(get_context(), chat_id)
        chat = Chat(id=chat_id, type=ChatType(settings.chatType), title=settings.title)
        await refresh_bot_permissions(
            client, chat, ChatMember(user=client.me, status=ChatMemberStatus.LEFT)
        )
    except RPCError as exc:
        logger.warning(f"Could not refresh bot permissions for {chat_id}: {exc}")
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
        member = update.new_chat_member or ChatMember(user=client.me, status=ChatMemberStatus.LEFT)
        await refresh_bot_permissions(client, update.chat, member)

        if is_now_admin and not was_previously_admin:
            import asyncio

            from src.utils.admin_cache import sync_admins_from_telegram

            asyncio.create_task(sync_admins_from_telegram(client, chat_id, force=True))

        # Also send dashboard if promoted
        if not was_previously_admin and is_now_admin and update.from_user:
            import contextlib

            from src.plugins.admin_panel.handlers.commands import send_admin_dashboard

            with contextlib.suppress(Exception):
                await send_admin_dashboard(
                    client, update.from_user.id, chat_id, text_key="panel.promotion_notify"
                )

        raise ContinuePropagation

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
