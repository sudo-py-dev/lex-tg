import asyncio
import contextlib
import functools

from loguru import logger
from pyrogram import ContinuePropagation
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    QueryIdInvalid,
    RPCError,
)
from pyrogram.types import CallbackQuery, Message

from src.config import config
from src.plugins.admin_panel.handlers.ai_kbs import ai_menu_kb
from src.plugins.admin_panel.handlers.keyboards import ai_security_kb, channel_watermark_kb
from src.plugins.admin_panel.repository import get_chat_settings
from src.plugins.ai_assistant.repository import AIRepository
from src.utils.actions import AI_PROVIDERS, cycle_action
from src.utils.i18n import at
from src.utils.media import parse_watermark_config


def _panel_lang_id(is_pm: bool, user_id: int, chat_id: int) -> int:
    return user_id if is_pm else chat_id


def _plain(text: str) -> str:
    """Remove markdown-style markers for callback answers."""
    return (
        text.replace("**", "")
        .replace("__", "")
        .replace("`", "")
        .replace("||", "")
        .replace("[", "")
        .replace("]", "")
    )


def _next_ai_provider(current_provider: str) -> str:
    return cycle_action(current_provider, AI_PROVIDERS, default_action=AI_PROVIDERS[0])


def safe_callback(func):
    """
    Decorator to safely handle common Telegram RPC errors in callback handlers.
    Suppresses MessageNotModified, QueryIdInvalid, and automatically handles FloodWait.
    """

    @functools.wraps(func)
    async def wrapper(client, callback: CallbackQuery, *args, **kwargs):
        try:
            return await func(client, callback, *args, **kwargs)
        except (QueryIdInvalid, MessageNotModified):
            # Silence expected errors
            pass
        except ContinuePropagation:
            # Re-raise to let other handlers process this event
            raise
        except FloodWait as e:
            # Auto-retry on flood wait
            await asyncio.sleep(int(e.value) + 1)
            return await wrapper(client, callback, *args, **kwargs)
        except (RPCError, Exception) as e:
            # Log other errors with full traceback and answer with a generic error if possible
            logger.opt(exception=True).error(f"Error in {func.__name__}: {e}")
            with contextlib.suppress(Exception):
                await callback.answer(
                    _plain(await at(callback.from_user.id, "panel.error_generic")), show_alert=True
                )

    return wrapper


async def safe_edit(event: CallbackQuery | Message, text: str = None, reply_markup=None, **kwargs):
    """
    Safely edit message text or reply_markup while ignoring common errors.
    Supports both CallbackQuery (event.message) and direct Message objects.
    """

    msg = event.message if not isinstance(event, Message) else event

    with contextlib.suppress(MessageNotModified, RPCError):
        if text:
            await msg.edit_text(text, reply_markup=reply_markup, **kwargs)
        else:
            await msg.edit_reply_markup(reply_markup=reply_markup)


async def _render_ai_panel(
    callback: CallbackQuery, ctx, chat_id: int, at_id: int, user_id: int
) -> None:
    s = await AIRepository.get_settings(ctx, chat_id)
    provider = (s.provider if s else "openai").upper()
    is_enabled = s.isAssistantEnabled if s else False
    model = (s.modelId if s else "N/A") or "N/A"
    api_key = "****" if (s and s.apiKey) else await at(at_id, "panel.not_set")
    status_text = await at(at_id, f"panel.status_{'enabled' if is_enabled else 'disabled'}")
    kb = await ai_menu_kb(chat_id, user_id=user_id)
    await safe_edit(
        callback,
        await at(
            at_id,
            "panel.ai_text",
            status=status_text,
            provider=provider,
            model=model,
            api_key=api_key,
        ),
        reply_markup=kb,
    )


async def _render_ai_guard_panel(
    callback: CallbackQuery, ctx, chat_id: int, at_id: int, user_id: int
) -> str:
    from src.db.repositories.ai_guard import get_ai_guard_settings

    s = await get_ai_guard_settings(ctx, chat_id)
    text_status = await at(at_id, f"panel.status_{'enabled' if s.isTextEnabled else 'disabled'}")
    media_status = await at(at_id, f"panel.status_{'enabled' if s.isImageEnabled else 'disabled'}")
    api_key_status = "****" if s.apiKey else await at(at_id, "panel.not_set")
    action_label = await at(at_id, f"action.{s.action}")
    await safe_edit(
        callback,
        await at(
            at_id,
            "panel.ai_guard_text",
            text_status=text_status,
            media_status=media_status,
            api_key=api_key_status,
            action=action_label,
            model=config.AI_GUARD_MODEL,
        ),
        reply_markup=await ai_security_kb(ctx, chat_id, user_id),
    )
    return action_label


async def _render_channel_watermark_panel(
    callback: CallbackQuery,
    ctx,
    channel_id: int,
    user_id: int,
    ui_id: int,
) -> None:
    settings = await get_chat_settings(ctx, channel_id)
    cfg = parse_watermark_config(settings.watermarkText)
    video_limit_note = (
        await at(ui_id, "panel.wm_video_limit_note", size_mb=config.VIDEO_WATERMARK_MAX_SIZE_MB)
        if config.ENABLE_VIDEO_WATERMARK
        else ""
    )
    await safe_edit(
        callback,
        await at(
            ui_id,
            "panel.channel_watermark_text",
            image_status=await at(
                ui_id, "panel.status_enabled" if cfg.image_enabled else "panel.status_disabled"
            ),
            has_image=await at(ui_id, "common.yes" if settings.watermarkImage else "common.no"),
            location=await at(
                ui_id, f"panel.wm_location_{settings.watermarkPosition or 'bottom_right'}"
            ),
            opacity=int(
                (settings.watermarkOpacity if settings.watermarkOpacity is not None else 0.7) * 100
            ),
            size=settings.watermarkSize or 10,
            text=cfg.text or "-",
            color=await at(ui_id, f"panel.wm_color_{cfg.color}"),
            style=await at(ui_id, f"panel.wm_style_{cfg.style}"),
            video_status=await at(
                ui_id, "panel.status_enabled" if cfg.video_enabled else "panel.status_disabled"
            ),
            video_quality=await at(ui_id, f"panel.wm_quality_{cfg.video_quality}"),
            video_motion=await at(ui_id, f"panel.wm_motion_{cfg.video_motion}"),
            video_available=await at(
                ui_id,
                "panel.wm_video_available_yes"
                if config.ENABLE_VIDEO_WATERMARK
                else "panel.wm_video_available_no",
            ),
            video_limit_note=video_limit_note,
        ),
        reply_markup=await channel_watermark_kb(ctx, channel_id, user_id),
    )
