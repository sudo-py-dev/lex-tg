import contextlib

from loguru import logger
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import LinkPreviewOptions, Message

from src.core.bot import bot
from src.core.context import get_context
from src.utils.decorators import safe_handler
from src.utils.formatters import TelegramFormatter
from src.utils.i18n import at
from src.utils.input import finalize_input_capture, is_waiting_for_input

from .conversation import (
    compact_history,
    conversation_lock,
    conversation_scope,
    is_addressed,
    request_content,
    typing_indicator,
)
from .prompts import build_system_prompt
from .repository import AIRepository
from .service import DEFAULT_MODELS, AIService, AIServiceError
from .telegram_markdown import render_pyrogram_html


@bot.on_message(filters.group & ~filters.service & ~filters.bot, group=100)
@safe_handler
async def ai_message_handler(client: Client, message: Message):
    if not client.me or not is_addressed(message, client.me):
        return
    ctx = get_context()
    settings = await AIRepository.get_runtime_settings(ctx, message.chat.id)
    if not settings or not settings.isAssistantEnabled or not settings.apiKey:
        return
    scope = conversation_scope(message)
    try:
        async with conversation_lock(scope):
            # A queued request must respect disabling or changing the assistant.
            settings = await AIRepository.get_runtime_settings(ctx, message.chat.id)
            if not settings or not settings.isAssistantEnabled or not settings.apiKey:
                return
            history = await AIRepository.get_conversation(ctx, *scope)
            current = {"role": "user", "content": request_content(message, client.me)}
            provider = (settings.provider or "openai").lower()
            model = settings.modelId or DEFAULT_MODELS.get(provider)
            if not model:
                raise AIServiceError("AI model is not configured.", status_code=400)
            prompt = build_system_prompt(
                client.me.first_name, client.me.username or "", settings.systemPrompt
            )
            budget = 6000 if provider == "groq" else 14000
            async with typing_indicator(client, message):
                try:
                    response = await AIService.call_ai(
                        provider,
                        settings.apiKey,
                        model,
                        prompt,
                        settings.customInstruction,
                        compact_history(history, max_chars=budget) + [current],
                    )
                except AIServiceError as exc:
                    if not exc.too_large:
                        raise
                    # Keep the latest question intact; reduce only older conversation history.
                    response = await AIService.call_ai(
                        provider,
                        settings.apiKey,
                        model,
                        prompt,
                        settings.customInstruction,
                        compact_history(history, max_messages=4, max_chars=2500) + [current],
                    )
                if not response or not response.strip():
                    raise AIServiceError("AI provider returned no text.")
                sent = await TelegramFormatter.send_safe(
                    client,
                    message.chat.id,
                    render_pyrogram_html(response),
                    reply_to_message_id=message.id,
                    parse_mode=ParseMode.HTML,
                    message_thread_id=scope[1] or None,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
                if sent:
                    await AIRepository.save_turn(
                        ctx, *scope, message.id, current["content"], response
                    )
    except Exception as exc:
        # Do not echo raw provider failures, secrets, or user prompts to the group.
        logger.warning("AI request failed in chat {} ({})", message.chat.id, type(exc).__name__)
        key = "ai.unavailable"
        if isinstance(exc, AIServiceError):
            if exc.status_code == 429:
                key = "ai.rate_limited"
            elif exc.too_large:
                key = "ai.request_too_long"
            elif exc.status_code in {400, 401, 403, 404}:
                key = "ai.configuration_error"
        with contextlib.suppress(Exception):
            await message.reply_text(await at(message.chat.id, key))


@bot.on_message(filters.command("resetai") & filters.group, group=99)
@safe_handler
async def reset_ai_conversation(client: Client, message: Message):
    ctx = get_context()
    scope = conversation_scope(message)
    async with conversation_lock(scope):
        await AIRepository.clear_conversation(ctx, *scope)
    await message.reply_text(await at(message.chat.id, "ai.conversation_reset"))


AI_FIELDS = ["aiApiKey", "aiModelId", "aiSystemPrompt", "aiInstruction"]


@bot.on_message(filters.private & is_waiting_for_input(AI_FIELDS), group=-50)
@safe_handler
async def ai_settings_handler(client: Client, message: Message):
    st = message.input_state
    cid, fld, uid = st["chat_id"], st["field"], message.from_user.id
    ctx, val = get_context(), (message.text or "").strip()
    if not val:
        return await message.reply(await at(uid, "panel.input_invalid_string"))

    mapping = {
        "aiApiKey": "apiKey",
        "aiModelId": "modelId",
        "aiSystemPrompt": "systemPrompt",
        "aiInstruction": "customInstruction",
    }
    await AIRepository.update_settings(ctx, cid, **{mapping.get(fld, fld): val})

    from src.plugins.admin_panel.handlers.ai_kbs import ai_menu_kb

    kb = await ai_menu_kb(cid, user_id=uid)
    s = await AIRepository.get_settings(ctx, cid)
    is_e, pvd, mod = (
        (s.isAssistantEnabled if s else False),
        (s.provider if s else "openai").upper(),
        (s.modelId if s else "N/A") or "N/A",
    )
    ake = "****" if (s and s.apiKey) else await at(uid, "panel.not_set")

    txt = await at(
        uid,
        "panel.ai_text",
        status=await at(uid, f"panel.status_{'enabled' if is_e else 'disabled'}"),
        provider=pvd,
        model=mod,
        api_key=ake,
    )
    ok = await at(uid, "panel.input_success")
    if fld == "aiModelId":
        ok = await at(uid, "panel.ai_model_set", model=mod)
    await finalize_input_capture(
        client, message, uid, st["prompt_msg_id"], txt, kb, success_text=ok
    )
