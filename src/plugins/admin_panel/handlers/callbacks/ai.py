from pyrogram import Client, filters
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.ai_kbs import model_selection_kb
from src.plugins.admin_panel.handlers.callbacks.common import (
    _next_ai_provider,
    _panel_lang_id,
    _plain,
    _render_ai_guard_panel,
    _render_ai_panel,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import ai_security_kb
from src.plugins.ai_assistant.repository import AIRepository
from src.plugins.ai_assistant.service import DEFAULT_MODELS as AI_PROVIDER_DEFAULT_MODELS
from src.utils.actions import AI_GUARD_ACTIONS, cycle_action
from src.utils.i18n import at
from src.utils.input import capture_next_input


@bot.on_callback_query(filters.regex(r"^panel:ai:(.*)"))
@admin_panel_context
@safe_callback
async def on_ai_settings(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    ctx = ap_ctx.ctx
    sub = callback.matches[0].group(1)

    if sub == "toggle":
        s = await AIRepository.get_settings(ctx, chat_id)
        cur = s.isAssistantEnabled if s else False
        await AIRepository.update_settings(ctx, chat_id, isAssistantEnabled=not cur)
        await _render_ai_panel(callback, ctx, chat_id, at_id, user_id)
    elif sub == "cycle_provider":
        s = await AIRepository.get_settings(ctx, chat_id)
        cur = s.provider if s else "openai"
        nxt = _next_ai_provider(cur)
        await AIRepository.update_settings(
            ctx, chat_id, provider=nxt, modelId=AI_PROVIDER_DEFAULT_MODELS[nxt]
        )
        await _render_ai_panel(callback, ctx, chat_id, at_id, user_id)
    elif sub == "model_list":
        s = await AIRepository.get_settings(ctx, chat_id)
        provider = s.provider if s else "openai"
        kb = await model_selection_kb(provider, chat_id, user_id=user_id if ap_ctx.is_pm else None)
        await safe_edit(
            callback,
            await at(at_id, "panel.ai_select_model_text", provider=provider.upper()),
            reply_markup=kb,
        )
    elif sub.startswith("set_model:"):
        model_id = sub.split(":")[1]
        await AIRepository.update_settings(ctx, chat_id, modelId=model_id)
        await callback.answer(_plain(await at(at_id, "panel.ai_model_set", model=model_id)))
        await _render_ai_panel(callback, ctx, chat_id, at_id, user_id)
    elif sub == "clear_ctx":
        await AIRepository.clear_context(ctx, chat_id)
        await callback.answer(_plain(await at(at_id, "panel.ai_ctx_cleared")))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_ai_guard$"))
@admin_panel_context
@safe_callback
async def on_toggle_ai_guard(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.ai_guard import get_ai_guard_settings, update_ai_guard_settings

    ctx = ap_ctx.ctx
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    s = await get_ai_guard_settings(ctx, chat_id)
    if not s.isTextEnabled and not s.apiKey:
        await callback.answer(
            _plain(await at(callback.from_user.id, "panel.ai_guard_key_required")), show_alert=True
        )
        return

    await update_ai_guard_settings(ctx, chat_id, isTextEnabled=not s.isTextEnabled)
    await _render_ai_guard_panel(callback, ctx, chat_id, at_id, callback.from_user.id)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_ai_image_guard$"))
@admin_panel_context
@safe_callback
async def on_toggle_ai_image_guard(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.ai_guard import get_ai_guard_settings, update_ai_guard_settings

    ctx = ap_ctx.ctx
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    s = await get_ai_guard_settings(ctx, chat_id)
    if not s.isImageEnabled and not s.apiKey:
        await callback.answer(
            _plain(await at(callback.from_user.id, "panel.ai_guard_key_required")), show_alert=True
        )
        return

    await update_ai_guard_settings(ctx, chat_id, isImageEnabled=not s.isImageEnabled)
    await _render_ai_guard_panel(callback, ctx, chat_id, at_id, callback.from_user.id)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:cycle_ai_guard_action$"))
@admin_panel_context
@safe_callback
async def on_cycle_ai_guard_action(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.ai_guard import get_ai_guard_settings, update_ai_guard_settings

    ctx = ap_ctx.ctx
    chat_id = ap_ctx.chat_id

    s = await get_ai_guard_settings(ctx, chat_id)
    next_action = cycle_action(s.action, AI_GUARD_ACTIONS, default_action="delete")

    await update_ai_guard_settings(ctx, chat_id, action=next_action)
    action_label = await _render_ai_guard_panel(
        callback,
        ctx,
        chat_id,
        _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
        callback.from_user.id,
    )
    await callback.answer(
        _plain(await at(callback.from_user.id, "panel.ai_guard_action_set", action=action_label))
    )


@bot.on_callback_query(filters.regex(r"^panel:set_groq_key$"))
@admin_panel_context
@safe_callback
async def on_set_groq_key(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)

    await capture_next_input(user_id, chat_id, "groqKey", prompt_msg_id=callback.message.id)
    await safe_edit(
        callback,
        await at(at_id, "panel.input_prompt_groqKey"),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        await at(at_id, "common.btn_cancel"),
                        callback_data="panel:category:ai_security",
                    )
                ]
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:ai_guard_setup$"))
@admin_panel_context
@safe_callback
async def on_ai_guard_setup(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.config import config

    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    await safe_edit(
        callback,
        await at(at_id, "panel.ai_guard_setup_guide", model=config.AI_GUARD_MODEL),
        reply_markup=await ai_security_kb(ap_ctx.ctx, ap_ctx.chat_id, callback.from_user.id),
        disable_web_page_preview=True,
    )
    await callback.answer()
