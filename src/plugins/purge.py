import asyncio
import contextlib
from uuid import uuid4

from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import (
    FloodWait,
    Forbidden,
    MessageDeleteForbidden,
    MessageIdInvalid,
    MessageNotModified,
    RPCError,
)
from pyrogram.types import (
    CallbackQuery,
    ChatMember,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.db.repositories.chats import get_chat_info
from src.utils.decorators import admin_permission_required, safe_handler
from src.utils.i18n import at
from src.utils.input import finalize_input_capture, is_waiting_for_input
from src.utils.local_cache import get_cache
from src.utils.panel_session import bind_panel, get_panel_session
from src.utils.permissions import Permission, has_permission


class PurgePlugin(Plugin):
    """Plugin to delete large amounts of messages (purge) in a chat."""

    name = "purge"
    priority = 100

    async def setup(self, client: Client, ctx) -> None:
        pass


@bot.on_message(filters.command("purge") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_DELETE)
async def purge_handler(client: Client, message: Message) -> None:
    """Purge messages between the replied message and the /purge command."""
    if not await has_permission(client, message.chat.id, Permission.CAN_DELETE):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if not message.reply_to_message:
        await message.reply(await at(message.chat.id, "purge.usage"))
        return

    message_ids = []
    start_id = message.reply_to_message.id
    end_id = message.id

    for msg_id in range(start_id, end_id + 1):
        message_ids.append(msg_id)
        if len(message_ids) >= 100:
            try:
                await client.delete_messages(message.chat.id, message_ids)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                with contextlib.suppress(Exception):
                    await client.delete_messages(message.chat.id, message_ids)
            except (Forbidden, RPCError):
                pass
            message_ids = []
            await asyncio.sleep(0.5)

    if message_ids:
        try:
            await client.delete_messages(message.chat.id, message_ids)
        except FloodWait as e:
            await asyncio.sleep(e.value + 1)
            with contextlib.suppress(Exception):
                await client.delete_messages(message.chat.id, message_ids)
        except (Forbidden, RPCError):
            pass

    status = await message.reply(
        await at(message.chat.id, "purge.done", count=end_id - start_id + 1)
    )
    await asyncio.sleep(3)
    await status.delete()


@bot.on_message(filters.command("del") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_DELETE)
async def del_handler(client: Client, message: Message) -> None:
    """Delete a single message that is replied to."""
    if not await has_permission(client, message.chat.id, Permission.CAN_DELETE):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if not message.reply_to_message:
        return
    await asyncio.gather(message.delete(), message.reply_to_message.delete())


@bot.on_message(filters.command("purgeme") & filters.group)
@safe_handler
async def purgeme_handler(client: Client, message: Message) -> None:
    """Purge the last N messages sent by the user themselves."""
    if len(message.command) < 2:
        return
    try:
        n = int(message.command[1])
    except ValueError:
        return

    if n > 100:
        n = 100

    message_ids = []
    async for msg in client.get_chat_history(message.chat.id, limit=n + 10):
        if msg.from_user and msg.from_user.id == message.from_user.id:
            message_ids.append(msg.id)
            if len(message_ids) >= n:
                break

    if message_ids:
        await client.delete_messages(message.chat.id, message_ids)


# --- Admin Panel Input Handlers ---


@bot.on_message(filters.private & is_waiting_for_input("purgeMessagesCount"), group=-50)
@safe_handler
async def purge_messages_input_handler(client: Client, message: Message) -> None:
    state = message.input_state
    chat_id = state["chat_id"]
    user_id = message.from_user.id
    value = (message.text or "").strip()
    if not value.isascii() or not value.isdecimal() or len(value) > 4:
        await message.reply(await at(user_id, "panel.purge_invalid_count"))
        return

    count = int(value)
    if not 1 <= count <= 1000:
        await message.reply(await at(user_id, "panel.purge_invalid_count"))
        return

    _, title = await get_chat_info(get_context(), chat_id)
    token = state.get("capture_id") or uuid4().hex
    cache = get_cache()
    if not await cache.delete_if_value(f"panel_input:{user_id}", message.input_capture_value):
        return
    await cache.set(f"purge_confirm:{user_id}:{token}", (chat_id, count), ttl=300)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.purge_confirm_button", count=count),
                    callback_data=f"panel:purge_confirm:yes:{token}",
                ),
                InlineKeyboardButton(
                    await at(user_id, "common.btn_cancel"),
                    callback_data=f"panel:purge_confirm:no:{token}",
                ),
            ]
        ]
    )
    await finalize_input_capture(
        client,
        message,
        user_id,
        state["prompt_msg_id"],
        await at(user_id, "panel.purge_confirm_text", title=title, count=count),
        kb,
    )


def _can_purge(member: ChatMember, chat_type: ChatType) -> bool:
    return member.status == ChatMemberStatus.OWNER or (
        member.status == ChatMemberStatus.ADMINISTRATOR
        and (
            chat_type == ChatType.GROUP
            or (member.privileges is not None and member.privileges.can_delete_messages)
        )
    )


async def _delete_purge_batch(client: Client, chat_id: int, ids: list[int]) -> int:
    if not ids:
        return 0
    try:
        try:
            await client.delete_messages(chat_id, ids)
        except FloodWait as error:
            if error.value > 5:
                return 0
            await asyncio.sleep(error.value + 1)
            await client.delete_messages(chat_id, ids)
    except (MessageDeleteForbidden, MessageIdInvalid):
        if len(ids) == 1:
            return 0
        midpoint = len(ids) // 2
        return await _delete_purge_batch(
            client, chat_id, ids[:midpoint]
        ) + await _delete_purge_batch(client, chat_id, ids[midpoint:])
    except RPCError:
        return 0
    return len(ids)


@bot.on_callback_query(filters.regex(r"^panel:purge_confirm:(yes|no):([0-9a-f]{32})$"))
@safe_handler
async def confirm_panel_purge(client: Client, callback: CallbackQuery) -> None:
    message = callback.message
    if not message or message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return

    user_id = callback.from_user.id
    choice, token = callback.matches[0].groups()
    cache = get_cache()
    key = f"purge_confirm:{user_id}:{token}"
    pending = await cache.get(key)
    back = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "panel.btn_back"), callback_data="panel:category:moderation"
                )
            ]
        ]
    )

    async def finish(text: str) -> None:
        try:
            await message.edit_text(text, reply_markup=back)
        except MessageNotModified:
            return
        except RPCError:
            chat_id, page = await get_panel_session(user_id, message.id)
            if pending and chat_id is None:
                chat_id = pending[0]
            replacement = await client.send_message(user_id, text, reply_markup=back)
            if chat_id is not None:
                await bind_panel(user_id, replacement.id, chat_id, page)

    if pending is None:
        await callback.answer(await at(user_id, "panel.input_inactive"), show_alert=True)
        await message.edit_reply_markup(reply_markup=back)
        return
    if not await cache.delete_if_value(key, pending):
        # Another tap already took ownership. Let it render the result.
        await callback.answer()
        return

    chat_id, count = pending
    if choice == "no":
        await callback.answer()
        await finish(await at(user_id, "panel.input_cancelled"))
        return

    try:
        chat = await client.get_chat(chat_id)
        actor = await client.get_chat_member(chat_id, user_id)
        if not _can_purge(actor, chat.type):
            error_key = "error.admin_no_permission"
        else:
            bot_member = await client.get_chat_member(chat_id, client.me.id)
            error_key = None if _can_purge(bot_member, chat.type) else "error.bot_no_permission"
    except RPCError:
        error_key = "panel.purge_permission_lookup_failed"

    if error_key:
        text = await at(user_id, error_key)
        await callback.answer(text, show_alert=True)
        await finish(text)
        return

    await callback.answer()
    with contextlib.suppress(RPCError):
        await message.edit_text(await at(user_id, "panel.purge_in_progress"))

    accepted = 0
    try:
        marker = await client.send_message(chat_id, await at(chat_id, "panel.purge_in_progress"))
        low = max(1, marker.id - count)
        with contextlib.suppress(RPCError):
            await marker.delete()
        for top in range(marker.id - 1, low - 1, -100):
            batch = list(range(top, max(low - 1, top - 100), -1))
            candidates = await client.get_messages(chat_id, batch, replies=0)
            # Basic groups can share the account's message ID space with other chats.
            ids = [
                item.id
                for item in candidates
                if item and item.chat and item.chat.id == chat_id and item.id in batch
            ]
            accepted += await _delete_purge_batch(client, chat_id, ids)
    except RPCError:
        logger.exception("Could not complete panel purge in chat {}", chat_id)

    result = "done" if accepted == count else "partial" if accepted else "failed"
    await finish(await at(user_id, f"panel.purge_result_{result}", accepted=accepted, count=count))


register(PurgePlugin())
