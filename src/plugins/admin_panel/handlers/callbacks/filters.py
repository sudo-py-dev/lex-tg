import asyncio
import json

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait,
    MessageIdInvalid,
    QueryIdInvalid,
)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    _plain,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import filter_options_kb, filters_menu_kb
from src.utils.i18n import at
from src.utils.input import capture_next_input
from src.utils.local_cache import get_cache


@bot.on_callback_query(filters.regex(r"^panel:filters:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_filters_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0
    kb = await filters_menu_kb(
        ap_ctx.ctx, chat_id, page=page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.filters_text"), reply_markup=kb)

    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:add_filter:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_add_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.filters import get_filters_count

    chat_id = ap_ctx.chat_id
    user_id = callback.from_user.id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    count = await get_filters_count(ap_ctx.ctx, chat_id)
    if count >= 150:
        await callback.answer(_plain(await at(at_id, "filter.limit_reached")), show_alert=True)
        return

    await capture_next_input(
        user_id, chat_id, "filterKeyword", prompt_msg_id=callback.message.id, page=page
    )
    await safe_edit(
        callback,
        await at(at_id, "panel.input_prompt_filterKeyword"),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        await at(at_id, "common.btn_cancel"),
                        callback_data=f"panel:cancel_input:filters:{page}",
                    )
                ]
            ]
        ),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:edit_filter:(\d+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_edit_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    f_id = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)

    from src.db.models import Filter

    async with ap_ctx.ctx.db() as session:
        f_obj = await session.get(Filter, f_id)
        if not f_obj or f_obj.chatId != chat_id:
            await callback.answer(_plain(await at(at_id, "panel.error_generic")), show_alert=True)
            return

        r = get_cache()
        await r.set(f"temp_filter_kw:{user_id}", f_obj.keyword, ttl=600)
        await r.set(
            f"temp_filter_resp:{user_id}",
            json.dumps({"text": f_obj.text, "type": f_obj.responseType, "file_id": f_obj.fileId}),
            ttl=600,
        )
        await r.set(f"temp_filter_settings:{user_id}", json.dumps(f_obj.settings), ttl=600)
        await r.set(f"temp_filter_edit_id:{user_id}", str(f_id), ttl=600)

        await capture_next_input(
            user_id, chat_id, "filterResponse", prompt_msg_id=callback.message.id, page=page
        )
        await safe_edit(
            callback,
            await at(at_id, "panel.input_prompt_filterResponse", keyword=f_obj.keyword),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            await at(at_id, "common.btn_cancel"),
                            callback_data=f"panel:cancel_input:filters:{page}",
                        )
                    ]
                ]
            ),
        )
        await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:delete_filter:(\d+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_delete_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    f_id = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    from src.db.repositories.filters import remove_filter_by_id

    success = await remove_filter_by_id(ap_ctx.ctx, f_id, chat_id=chat_id)
    if success:
        await callback.answer(_plain(await at(at_id, "common.done")))
    else:
        await callback.answer(_plain(await at(at_id, "panel.error_generic")), show_alert=True)

    kb = await filters_menu_kb(
        ap_ctx.ctx, chat_id, page=page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    try:
        await safe_edit(callback, reply_markup=kb)
    except (MessageIdInvalid, QueryIdInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        pass


@bot.on_callback_query(filters.regex(r"^panel:clear_filters$"))
@admin_panel_context
@safe_callback
async def on_clear_filters(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.filters import remove_all_filters

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    await remove_all_filters(ap_ctx.ctx, chat_id)
    await callback.answer(_plain(await at(at_id, "common.done")))
    kb = await filters_menu_kb(
        ap_ctx.ctx, chat_id, page=0, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    try:
        await safe_edit(callback, reply_markup=kb)
    except (MessageIdInvalid, QueryIdInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        pass


@bot.on_callback_query(filters.regex(r"^panel:toggle_filter:(\w+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_toggle_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    mode = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    user_id = callback.from_user.id

    r = get_cache()
    settings_raw = await r.get(f"temp_filter_settings:{user_id}")
    settings = json.loads(settings_raw) if settings_raw else {}

    if mode == "admin":
        settings["isAdminOnly"] = not settings.get("isAdminOnly", False)
    elif mode == "case":
        settings["caseSensitive"] = not settings.get("caseSensitive", False)
    elif mode == "match":
        settings["matchMode"] = "full" if settings.get("matchMode") == "contains" else "contains"

    await r.set(f"temp_filter_settings:{user_id}", json.dumps(settings), ttl=600)
    kb = await filter_options_kb(ap_ctx.ctx, ap_ctx.chat_id, user_id, page)
    try:
        await safe_edit(callback, reply_markup=kb)
    except (MessageIdInvalid, QueryIdInvalid):
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        pass
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:save_filter:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_save_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    page = int(callback.matches[0].group(1))
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    r = get_cache()

    keyword = await r.get(f"temp_filter_kw:{user_id}")
    resp_raw = await r.get(f"temp_filter_resp:{user_id}")
    settings_raw = await r.get(f"temp_filter_settings:{user_id}")

    if not keyword or not resp_raw:
        await callback.answer(_plain(await at(at_id, "panel.error_generic")), show_alert=True)
        return

    resp_data = json.loads(resp_raw)
    settings = json.loads(settings_raw) if settings_raw else {}

    from src.db.repositories.filters import add_filter, update_filter_by_id

    edit_id_raw = await r.get(f"temp_filter_edit_id:{user_id}")
    if edit_id_raw:
        updated = await update_filter_by_id(
            ap_ctx.ctx,
            int(edit_id_raw),
            keyword,
            text=resp_data.get("text") or "",
            response_type=resp_data["type"],
            file_id=resp_data.get("file_id"),
            settings=settings,
            chat_id=chat_id,
        )
        if not updated:
            await callback.answer(_plain(await at(at_id, "panel.error_generic")), show_alert=True)
            return
    else:
        try:
            await add_filter(
                ap_ctx.ctx,
                chat_id,
                keyword,
                text=resp_data.get("text") or "",
                response_type=resp_data["type"],
                file_id=resp_data.get("file_id"),
                settings=settings,
            )
        except ValueError as e:
            if str(e) == "filter_already_exists":
                await callback.answer(
                    _plain(await at(at_id, "filter.err_already_exists")), show_alert=True
                )
                return
            raise e

    await r.delete(f"temp_filter_kw:{user_id}")
    await r.delete(f"temp_filter_resp:{user_id}")
    await r.delete(f"temp_filter_settings:{user_id}")
    await r.delete(f"temp_filter_edit_id:{user_id}")

    await callback.answer(_plain(await at(at_id, "panel.input_success")))
    kb = await filters_menu_kb(
        ap_ctx.ctx, chat_id, page=page, user_id=user_id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.filters_text"), reply_markup=kb)
