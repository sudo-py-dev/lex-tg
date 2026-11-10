import contextlib
import json

from pyrogram import Client, StopPropagation, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.bot import bot
from src.core.context import get_context
from src.core.plugin import Plugin, register
from src.db.repositories.filters import (
    add_filter,
    get_all_filters,
    remove_all_filters,
    remove_filter,
)
from src.utils.decorators import admin_permission_required, safe_handler
from src.utils.formatters import TelegramFormatter
from src.utils.i18n import at
from src.utils.input import (
    capture_next_input,
    finalize_input_capture,
    is_waiting_for_input,
)
from src.utils.local_cache import get_cache
from src.utils.message_rules import get_reply_rules
from src.utils.permissions import Permission, has_permission, is_admin
from src.utils.telegram_storage import extract_message_data


class FiltersPlugin(Plugin):
    """Plugin to manage custom auto-replies (filters) in groups."""

    name = "filters"
    priority = 100

    async def setup(self, client: Client, ctx) -> None:
        pass


@bot.on_message(filters.command("filter") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_RESTRICT)
async def add_filter_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_RESTRICT):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if len(message.command) < 2:
        return
    txt = message.text.split(None, 1)[1] if " " in message.text else ""
    kw, resp = "", ""
    if txt.startswith(('"', "'")):
        q = txt[0]
        if (idx := txt.find(q, 1)) != -1:
            kw, resp = txt[1:idx].lower(), txt[idx + 1 :].strip()
    if not kw:
        kw, resp = (
            message.command[1].lower(),
            (message.text.split(None, 2)[2] if len(message.command) > 2 else ""),
        )

    fid, rtype = None, "text"
    if message.reply_to_message:
        r = message.reply_to_message
        m = (
            r.photo
            or r.video
            or r.document
            or r.animation
            or r.sticker
            or r.audio
            or r.voice
            or r.video_note
        )
        if m:
            fid, rtype = m.file_id, m.__class__.__name__.lower()
            if not resp:
                resp = r.caption or ""
        elif not resp:
            resp = r.text or ""
    if not resp and not fid:
        return

    if len(kw) > 64:
        return await message.reply(await at(message.chat.id, "filter.keyword_too_long", limit=64))
    try:
        await add_filter(get_context(), message.chat.id, kw, resp, rtype, fid)
        await message.reply(await at(message.chat.id, "filter.added", keyword=kw))
    except ValueError as e:
        k = (
            "filter.limit_reached"
            if str(e) == "filter_limit_reached"
            else "filter.err_already_exists"
            if str(e) == "filter_already_exists"
            else "error.generic"
        )
        await message.reply(await at(message.chat.id, k))


@bot.on_message(filters.command("stop") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_RESTRICT)
async def stop_filter_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_RESTRICT):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if len(message.command) < 2:
        return
    kw = message.text.split(None, 1)[1].strip()
    if len(kw) >= 2 and kw[0] in {'"', "'"} and kw[-1] == kw[0]:
        kw = kw[1:-1]
    kw = kw.lower()
    if await remove_filter(get_context(), message.chat.id, kw):
        await message.reply(await at(message.chat.id, "filter.removed", keyword=kw))
    else:
        await message.reply(await at(message.chat.id, "filter.not_found", keyword=kw))


@bot.on_message(filters.command("stopall") & filters.group)
@safe_handler
@admin_permission_required(Permission.CAN_RESTRICT)
async def stopall_filters_handler(client: Client, message: Message) -> None:
    if not await has_permission(client, message.chat.id, Permission.CAN_RESTRICT):
        return await message.reply(await at(message.chat.id, "error.bot_no_permission"))
    if (c := await remove_all_filters(get_context(), message.chat.id)) > 0:
        await message.reply(await at(message.chat.id, "filter.stopall_done", count=c))
    else:
        await message.reply(await at(message.chat.id, "filter.stopall_empty"))


@bot.on_message(filters.command("filters") & filters.group)
@safe_handler
async def list_filters_handler(client: Client, message: Message) -> None:
    if not (fs := await get_all_filters(get_context(), message.chat.id)):
        return await message.reply(await at(message.chat.id, "filter.list_empty"))
    await message.reply(
        f"{await at(message.chat.id, 'filter.list_header')}\n"
        + "\n".join(f"• `{f.keyword}`" for f in fs)
    )


@bot.on_message(filters.group & filters.text, group=10)
@safe_handler
async def filters_interceptor(client: Client, message: Message) -> None:
    if not message.text or getattr(message, "command", None):
        return
    rules = await get_reply_rules(get_context(), message.chat.id)
    adm = None
    for f in rules:
        if not f.matches(message.text):
            continue
        if f.admin_only:
            if adm is None:
                sender = message.from_user or message.sender_chat
                adm = bool(sender) and await is_admin(client, message.chat.id, sender.id)
            if not adm:
                continue
        p = TelegramFormatter.parse_message(
            text=f.text,
            user=message.from_user,
            chat_id=message.chat.id,
            chat_title=message.chat.title,
            bot_username=client.me.username,
        )
        if f.file_id:
            await TelegramFormatter.send_media_parsed(
                client,
                message.chat.id,
                f.response_type,
                f.file_id,
                p,
                reply_to_message_id=message.id,
            )
        else:
            await TelegramFormatter.send_parsed(
                client, message.chat.id, p, reply_to_message_id=message.id
            )
        raise StopPropagation


# --- Admin Panel Input Handlers ---


@bot.on_message(filters.private & is_waiting_for_input("filterKeyword"), group=-50)
@safe_handler
async def filter_keyword_handler(client: Client, message: Message) -> None:
    state = message.input_state
    user_id = message.from_user.id
    chat_id = state["chat_id"]
    page = state["page"]
    prompt_msg_id = state["prompt_msg_id"]
    value = message.text

    keyword = str(value).lower().strip()
    if not keyword:
        await message.reply(await at(user_id, "panel.input_invalid_string"))
        return

    limit = 64
    if len(keyword) > limit:
        await message.reply(await at(user_id, "filter.keyword_too_long", limit=limit))
        return

    r = get_cache()
    await r.set(f"temp_filter_kw:{user_id}", keyword, ttl=300)

    await capture_next_input(user_id, chat_id, "filterResponse", prompt_msg_id, page)

    prompt_text = await at(user_id, "panel.input_prompt_filterResponse", keyword=keyword)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(user_id, "common.btn_cancel"), callback_data=f"panel:filters:{page}"
                )
            ]
        ]
    )

    if prompt_msg_id:
        await client.edit_message_text(user_id, prompt_msg_id, prompt_text, reply_markup=kb)
    else:
        await message.reply(prompt_text, reply_markup=kb)

    with contextlib.suppress(Exception):
        await message.delete()


@bot.on_message(filters.private & is_waiting_for_input("filterResponse"), group=-50)
@safe_handler
async def filter_response_handler(client: Client, message: Message) -> None:
    state = message.input_state
    user_id = message.from_user.id
    chat_id = state["chat_id"]
    page = state["page"]
    prompt_msg_id = state["prompt_msg_id"]
    ctx = get_context()

    r = get_cache()
    keyword = await r.get(f"temp_filter_kw:{user_id}")
    if not keyword:
        return

    all_fs = await get_all_filters(ctx, chat_id)
    if keyword not in [f.keyword for f in all_fs] and len(all_fs) >= 150:
        await message.reply(await at(user_id, "filter.limit_reached"))
        await r.delete(f"temp_filter_kw:{user_id}")
        return

    data = await extract_message_data(message)
    await r.set(f"temp_filter_resp:{user_id}", json.dumps(data), ttl=600)

    settings = {"matchMode": "contains", "caseSensitive": False, "isAdminOnly": False}
    await r.set(f"temp_filter_settings:{user_id}", json.dumps(settings), ttl=600)

    from src.plugins.admin_panel.handlers.keyboards import filter_options_kb

    kb = await filter_options_kb(ctx, chat_id, user_id, page)
    prompt_text = await at(user_id, "panel.filter_options_header", keyword=keyword)

    await finalize_input_capture(client, message, user_id, prompt_msg_id, prompt_text, kb)


register(FiltersPlugin())
