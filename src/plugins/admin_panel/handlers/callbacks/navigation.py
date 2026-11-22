from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    _render_ai_guard_panel,
    _render_ai_panel,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.commands import render_dashboard
from src.plugins.admin_panel.handlers.keyboards import (
    automation_category_kb,
    greetings_category_kb,
    moderation_category_kb,
    security_category_kb,
    settings_category_kb,
)
from src.utils.i18n import at


@bot.on_callback_query(filters.regex(r"^panel:main$"))
@admin_panel_context
@safe_callback
async def on_panel_main(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    text, kb = await render_dashboard(
        ap_ctx.ctx,
        ap_ctx.chat_id,
        callback.from_user.id if ap_ctx.is_pm else None,
        ap_ctx.chat_type,
        ap_ctx.chat_title,
        picker_page=ap_ctx.picker_page,
    )
    await safe_edit(callback, text, reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:category:(\w+)$"))
@admin_panel_context
@safe_callback
async def on_panel_category(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    cat = callback.matches[0].group(1)
    chat_type_str = ap_ctx.chat_type.name.lower() if ap_ctx.chat_type else "supergroup"
    is_pm = ap_ctx.is_pm

    if cat == "security":
        kb = await security_category_kb(
            chat_id, user_id=user_id if is_pm else None, chat_type=chat_type_str
        )
        title_key = (
            "panel.security_text_channel" if chat_type_str == "channel" else "panel.security_text"
        )
        await safe_edit(
            callback, await at(at_id, title_key, title=ap_ctx.chat_title), reply_markup=kb
        )
    elif cat == "moderation":
        kb = await moderation_category_kb(
            chat_id, user_id=user_id if is_pm else None, chat_type=chat_type_str
        )
        title_key = (
            "panel.moderation_text_channel"
            if chat_type_str == "channel"
            else "panel.moderation_text"
        )
        await safe_edit(
            callback, await at(at_id, title_key, title=ap_ctx.chat_title), reply_markup=kb
        )
    elif cat == "greetings":
        kb = await greetings_category_kb(
            chat_id, user_id=user_id if is_pm else None, chat_type=chat_type_str
        )
        title_key = (
            "panel.general_text_channel" if chat_type_str == "channel" else "panel.greetings_text"
        )
        await safe_edit(
            callback, await at(at_id, title_key, title=ap_ctx.chat_title), reply_markup=kb
        )
    elif cat == "automation":
        kb = await automation_category_kb(
            chat_id, user_id=user_id if is_pm else None, chat_type=chat_type_str
        )
        title_key = (
            "panel.scheduler_text_channel" if chat_type_str == "channel" else "panel.scheduler_text"
        )
        await safe_edit(
            callback, await at(at_id, title_key, title=ap_ctx.chat_title), reply_markup=kb
        )
    elif cat in ("settings", "general"):
        kb = await settings_category_kb(
            chat_id, user_id=user_id if is_pm else None, chat_type=chat_type_str
        )
        title_key = (
            "panel.general_text_channel" if chat_type_str == "channel" else "panel.settings_text"
        )
        await safe_edit(
            callback, await at(at_id, title_key, title=ap_ctx.chat_title), reply_markup=kb
        )
    elif cat == "ai":
        await _render_ai_panel(callback, ap_ctx.ctx, chat_id, at_id, user_id)
    elif cat == "ai_security":
        await _render_ai_guard_panel(callback, ap_ctx.ctx, chat_id, at_id, user_id)

    await callback.answer()
