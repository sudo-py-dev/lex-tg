from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.repository import resolve_chat_type
from src.plugins.admin_panel.validation import is_setting_allowed
from src.plugins.ai_assistant.repository import AIRepository
from src.utils.i18n import at
from src.utils.input import cancel_input_capture, capture_next_input
from src.utils.permissions import can_manage_blacklist


@bot.on_callback_query(filters.regex(r"^panel:input:(\w+):?(-?\d+)?$"))
@admin_panel_context
@safe_callback
async def on_panel_input(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    field = callback.matches[0].group(1)
    target_id_str = callback.matches[0].group(2)

    if field == "blacklistInput" and not await can_manage_blacklist(_, chat_id, user_id):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    logger.debug(f"Admin Panel: input action triggered for field {field} by user {user_id}")

    channel_routes = {
        "reactions": "channel_reactions",
        "signatureText": "channel_signature",
        "buttonsText": "channel_buttons",
        "watermarkText": "channel_watermark",
        "watermarkImage": "channel_watermark",
        "watermarkOpacity": "channel_watermark",
        "watermarkSize": "channel_watermark",
    }
    channel_route = channel_routes.get(field)
    if channel_route and target_id_str is None:
        await callback.answer(await at(ap_ctx.at_id, "panel.error_generic"), show_alert=True)
        return

    validate_chat_id = int(target_id_str) if channel_route else chat_id
    if validate_chat_id != chat_id:
        await callback.answer(await at(ap_ctx.at_id, "common.err_access_denied"), show_alert=True)
        return

    chat_type = await resolve_chat_type(ctx, validate_chat_id)
    if not is_setting_allowed(field, chat_type.name.lower()):
        await callback.answer(
            await at(user_id, "panel.setting_not_allowed_for_type"), show_alert=True
        )
        return

    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)

    page = 0
    if channel_route:
        cancel_cb = f"panel:{channel_route}:{validate_chat_id}"
    else:
        page = int(target_id_str) if target_id_str and target_id_str.isdigit() else 0
        cancel_map = {
            "floodThreshold": "panel:flood",
            "floodWindow": "panel:flood",
            "welcomeText": "panel:welcome",
            "rulesText": "panel:rules",
            "warnLimit": "panel:warns",
            "slowmode": "panel:slowmode",
            "raidThreshold": "panel:raid",
            "raidWindow": "panel:raid",
            "raidTime": "panel:raid",
            "raidActionTime": "panel:raid",
            "captchaTimeout": "panel:captcha",
            "gsbKey": "panel:urlscanner",
            "reminderText": "panel:reminders",
            "chatnightlockStart": "panel:chatnightlock",
            "chatnightlockEnd": "panel:chatnightlock",
            "cleanerInactive": "panel:cleaner",
            "cleanerRunTime": "panel:cleaner",
            "purgeMessagesCount": "panel:category:moderation",
        }
        if field.startswith("ai"):
            cancel_cb = "panel:category:ai"
        elif field == "blacklistInput":
            cancel_cb = f"panel:blacklist:{page}"
        elif field == "langblockInput":
            cancel_cb = f"panel:langblock:{page}"
        elif field == "stickerInput":
            cancel_cb = f"panel:stickers:{page}"
        else:
            cancel_cb = cancel_map.get(field, "panel:main")

    prompt_key = f"panel.input_prompt_{field}"

    if field == "aiApiKey":
        settings = await AIRepository.get_settings(ctx, chat_id)
        provider = (settings.provider if settings else "openai").upper()
        prompt_text = await at(at_id, prompt_key, provider=provider)
    else:
        prompt_text = await at(at_id, prompt_key)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "common.btn_cancel"),
                    callback_data=f"panel:cancel_input:{cancel_cb.removeprefix('panel:')}",
                )
            ]
        ]
    )
    expiry_note = await at(at_id, "panel.input_expires")
    await safe_edit(callback, f"{prompt_text}\n\n{expiry_note}", reply_markup=kb)
    await capture_next_input(
        user_id, validate_chat_id, field, prompt_msg_id=callback.message.id, page=page
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:cancel_input(?::([\w:-]+))?$"))
@safe_callback
async def on_cancel_input(_: Client, callback: CallbackQuery):
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer()
        return

    user_id = callback.from_user.id
    return_route = callback.matches[0].group(1) or "main"
    cancelled = await cancel_input_capture(user_id, callback.message.id)
    text_key = "panel.input_cancelled" if cancelled else "panel.input_inactive"
    await safe_edit(
        callback,
        await at(user_id, text_key),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        await at(user_id, "panel.btn_back"),
                        callback_data=f"panel:{return_route}",
                    )
                ]
            ]
        ),
    )
    await callback.answer()
