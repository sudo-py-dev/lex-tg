from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery

from src.core.bot import bot
from src.core.context import get_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    _plain,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import (
    channels_menu_kb,
    main_menu_kb,
    my_chats_menu_kb,
    my_groups_kb,
)
from src.plugins.admin_panel.repository import (
    get_chat_info,
    get_chat_settings,
    set_active_chat,
)
from src.utils.i18n import at


@bot.on_callback_query(filters.regex(r"^panel:close$"))
@safe_callback
async def on_panel_close(_: Client, callback: CallbackQuery):
    if callback.message:
        await callback.message.delete()
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:my_chats$"))
@safe_callback
async def on_my_chats(_: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    await safe_edit(
        callback,
        await at(user_id, "panel.main_text_user", user_id=user_id),
        reply_markup=await my_chats_menu_kb(user_id),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:list_groups$"))
@safe_callback
async def on_list_groups(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    ctx = get_context()
    kb = await my_groups_kb(ctx, client, user_id)
    await safe_edit(callback, await at(user_id, "panel.groups_list_title"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:list_channels$"))
@safe_callback
async def on_list_channels(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    ctx = get_context()
    kb = await channels_menu_kb(ctx, client, user_id)
    await safe_edit(callback, await at(user_id, "panel.channels_list_title"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:select_chat:(-?\d+)$"))
@safe_callback
async def on_select_chat(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    new_chat_id = int(callback.matches[0].group(1))

    from src.utils.admin_cache import is_admin

    if not await is_admin(client, new_chat_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    is_pm = callback.message.chat.type == ChatType.PRIVATE
    at_id = _panel_lang_id(is_pm, user_id, new_chat_id)
    chat_type, chat_title = await get_chat_info(ctx, new_chat_id)
    await set_active_chat(ctx, user_id, new_chat_id, chat_type=chat_type.name.lower())

    await safe_edit(
        callback,
        await at(at_id, "panel.main_text", user_id=user_id, title=chat_title),
        reply_markup=await main_menu_kb(
            new_chat_id,
            user_id=user_id if is_pm else None,
            chat_type=chat_type,
        ),
    )
    await callback.answer(_plain(await at(at_id, "panel.switch_chat", user_id=user_id)))


@bot.on_callback_query(filters.regex(r"^panel:select_channel:(-?\d+)$"))
@safe_callback
async def on_select_channel(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    from src.utils.admin_cache import is_admin

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    from src.plugins.admin_panel.handlers.keyboards import channel_settings_kb

    chat_type, _ = await get_chat_info(ctx, channel_id)
    if chat_type != ChatType.CHANNEL:
        await on_select_chat(client, callback)
        return

    await set_active_chat(ctx, user_id, channel_id, chat_type="channel")
    s = await get_chat_settings(ctx, channel_id)
    title = s.title or f"Channel {channel_id}"
    kb = await channel_settings_kb(ctx, channel_id, user_id)

    await safe_edit(
        callback,
        await at(user_id, "panel.channel_settings_text", title=title, id=channel_id),
        reply_markup=kb,
    )
    await callback.answer(_plain(await at(user_id, "panel.switch_chat", user_id=user_id)))


@bot.on_callback_query(filters.regex(r"^panel:language:user:?(\d+)?$"))
@safe_callback
async def on_user_language(_: Client, callback: CallbackQuery):
    from src.plugins.language import language_picker_kb

    user_id = callback.from_user.id
    ctx = get_context()
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    await safe_edit(
        callback,
        await at(user_id, "language.user_picker_header"),
        reply_markup=await language_picker_kb(ctx, user_id, scope="user", page=page),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:language_page:user:(\d+):(\d+)$"))
@safe_callback
async def on_user_language_page(_: Client, callback: CallbackQuery):
    from src.plugins.language import language_picker_kb

    ctx = get_context()
    user_id = callback.from_user.id
    target_id = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))

    await safe_edit(
        callback,
        await at(user_id, "language.user_picker_header"),
        reply_markup=await language_picker_kb(ctx, target_id, scope="user", page=page),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:language_search:user:(\d+)$"))
@safe_callback
async def on_user_language_search(_: Client, callback: CallbackQuery):
    from src.plugins.language import begin_language_search

    user_id = callback.from_user.id
    target_id = int(callback.matches[0].group(1))

    await begin_language_search(user_id, "user", target_id, prompt_msg_id=callback.message.id)
    await safe_edit(callback, await at(user_id, "language.search_prompt"))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:set_lang:user:(\d+):([^:]+)(?::(.*))?$"))
@safe_callback
async def on_user_language_set(_: Client, callback: CallbackQuery):
    from src.plugins.language import set_user_lang

    ctx = get_context()
    user_id = callback.from_user.id
    target_id = int(callback.matches[0].group(1))
    new_lang = callback.matches[0].group(2)
    mode = callback.matches[0].group(3)

    await set_user_lang(ctx, target_id, new_lang)

    if mode and mode.startswith("onboarding"):
        payload = mode.replace("onboarding:", "") if ":" in mode else None

        if payload and payload.startswith("settings_"):
            cid = payload.replace("settings_", "")
            if cid.startswith("-") and cid.lstrip("-").isdigit():
                from src.plugins.admin_panel.handlers import open_settings_panel

                await open_settings_panel(_, callback.message, int(cid))
                return await callback.answer(
                    _plain(await at(user_id, "panel.user_lang_set", lang=new_lang.upper()))
                )

        from src.plugins.admin import send_start_message

        await send_start_message(_, callback.message, edit=True)
        return await callback.answer(
            _plain(await at(user_id, "panel.user_lang_set", lang=new_lang.upper()))
        )

    await safe_edit(
        callback,
        await at(user_id, "panel.main_text_user", user_id=user_id),
        reply_markup=await my_chats_menu_kb(user_id),
    )
    await callback.answer(_plain(await at(user_id, "panel.user_lang_set", lang=new_lang.upper())))
