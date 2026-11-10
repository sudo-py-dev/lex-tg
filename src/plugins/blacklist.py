import re

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import InlineKeyboardMarkup, Message

from src.core.blacklist_defaults import describe_block_pattern
from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.db.repositories.blacklist import (
    add_blacklist,
    get_all_blacklist,
    remove_blacklist,
)
from src.utils.decorators import admin_permission_required, safe_handler
from src.utils.i18n import at
from src.utils.input import finalize_input_capture, is_waiting_for_input
from src.utils.message_rules import (
    detect_pattern_type,
    get_block_rules,
    get_block_settings,
    match_block,
)
from src.utils.moderation import execute_moderation_action, resolve_sender
from src.utils.permissions import Permission


class BlacklistPlugin(Plugin):
    """Plugin to manage blacklisted words and patterns in group chats."""

    name = "blacklist"
    priority = 100

    async def setup(self, client: Client, ctx) -> None:
        pass


@bot.on_message(filters.command(["addblacklist", "blacklistadd"]) & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_BAN)
async def add_blacklist_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2:
        return
    ctx, p = get_context(), message.text.split(None, 1)[1].strip()
    is_r, is_w, p = detect_pattern_type(p)
    try:
        if await add_blacklist(ctx, message.chat.id, p, is_regex=is_r, is_wildcard=is_w):
            await message.reply(await at(message.chat.id, "blacklist.added", pattern=p))
    except ValueError as e:
        k = (
            "blacklist.limit_reached"
            if str(e) == "blacklist_limit_reached"
            else "blacklist.err_already_exists"
            if str(e) == "blacklist_already_exists"
            else "panel.blacklist_invalid_regex"
            if str(e) == "blacklist_invalid_regex"
            else "error.generic"
        )
        await message.reply(await at(message.chat.id, k))


@bot.on_message(filters.command(["rmblacklist", "unblacklist"]) & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_BAN)
async def rm_blacklist_handler(client: Client, message: Message) -> None:
    if len(message.command) < 2:
        return
    ctx, p = get_context(), detect_pattern_type(message.text.split(None, 1)[1])[2]
    if await remove_blacklist(ctx, message.chat.id, p):
        await message.reply(await at(message.chat.id, "blacklist.removed", pattern=p))
    else:
        await message.reply(await at(message.chat.id, "blacklist.not_found"))


@bot.on_message(filters.command("blacklist") & filters.group)
@safe_handler
async def list_blacklist_handler(client: Client, message: Message) -> None:
    ctx = get_context()
    bl = await get_all_blacklist(ctx, message.chat.id)
    if not bl:
        return await message.reply(await at(message.chat.id, "blacklist.list_empty"))
    await message.reply(
        f"{await at(message.chat.id, 'blacklist.list_header')}\n"
        + "\n".join(f"• `{describe_block_pattern(b.pattern)}` ({b.action})" for b in bl)
    )


@bot.on_message(filters.group & (filters.text | filters.caption), group=-60)
@safe_handler
async def blacklist_interceptor(client: Client, message: Message) -> None:
    t = message.text or message.caption or ""
    ctx = get_context()
    rules = await get_block_rules(ctx, message.chat.id)
    if not rules:
        return
    s = await get_block_settings(ctx, message.chat.id)
    if (
        s.scan_buttons
        and message.reply_markup
        and isinstance(message.reply_markup, InlineKeyboardMarkup)
    ):
        for row in message.reply_markup.inline_keyboard:
            for b in row:
                t += f" {b.text if b.text else ''} {b.url if b.url else ''}"
    match = match_block(rules, t)
    if not match:
        return
    uid, _, white = await resolve_sender(client, message)
    if not uid or white:
        return
    if await execute_moderation_action(
        client,
        message,
        s.action,
        await at(message.chat.id, "blacklist.reason", pattern=match.pattern),
        "Blacklist",
        "blacklist.violation_notice",
        pattern=match.pattern,
    ):
        raise StopPropagation


# --- Admin Panel Input Handlers ---


@bot.on_message(filters.private & is_waiting_for_input("blacklistInput"), group=-50)
@safe_handler
async def blacklist_input_handler(client: Client, message: Message) -> None:
    s = message.input_state
    uid, cid, p = (
        message.from_user.id,
        s["chat_id"],
        str(message.text or message.caption or "").strip(),
    )
    if not p:
        return
    is_r, is_w, p = detect_pattern_type(p)
    if is_r:
        try:
            re.compile(p)
        except re.error:
            return await message.reply(await at(uid, "panel.blacklist_invalid_regex"))
    ctx = get_context()
    try:
        await add_blacklist(ctx, cid, p, is_regex=is_r, is_wildcard=is_w)
    except ValueError as e:
        k = (
            "blacklist.err_already_exists"
            if str(e) == "blacklist_already_exists"
            else "panel.blacklist_limit_reached"
            if str(e) == "blacklist_limit_reached"
            else "panel.blacklist_invalid_regex"
            if str(e) == "blacklist_invalid_regex"
            else "error.generic"
        )
        return await message.reply(await at(uid, k))
    from src.plugins.admin_panel.handlers.moderation_kbs import blacklist_kb

    await finalize_input_capture(
        client,
        message,
        uid,
        s["prompt_msg_id"],
        await at(uid, "panel.blacklist_text"),
        await blacklist_kb(ctx, cid, s["page"], user_id=uid),
        success_text=await at(uid, "panel.input_success"),
    )


register(BlacklistPlugin())
