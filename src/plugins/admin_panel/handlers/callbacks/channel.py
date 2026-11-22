import json
import math

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from src.config import config
from src.core.bot import bot
from src.core.context import get_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _plain,
    _render_channel_watermark_panel,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import (
    channel_reactions_kb,
    channel_settings_kb,
    channel_signature_kb,
)
from src.plugins.admin_panel.handlers.service_cleaner import (
    get_available_service_types,
    service_cleaner_kb,
    service_cleaner_types_kb,
)
from src.plugins.admin_panel.repository import (
    get_chat_settings,
    toggle_service_type,
    update_chat_setting,
)
from src.utils.actions import (
    BUTTON_STYLES,
    REACTION_MODES,
    VIDEO_MOTIONS,
    VIDEO_QUALITIES,
    WATERMARK_COLORS,
    WATERMARK_POSITIONS,
    WATERMARK_STYLES,
    ButtonStyle,
    ReactionMode,
    VideoMotion,
    VideoQuality,
    WatermarkColor,
    WatermarkPosition,
    WatermarkStyle,
    cycle_action,
)
from src.utils.i18n import at
from src.utils.media import build_watermark_config, parse_watermark_config
from src.utils.panel_session import get_panel_session
from src.utils.permissions import is_admin


@bot.on_callback_query(filters.regex(r"^panel:channel_settings:(-?\d+)$"))
@safe_callback
async def on_channel_settings(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    title = s.title or f"Channel {channel_id}"
    _, picker_page = await get_panel_session(user_id, callback.message.id)
    kb = await channel_settings_kb(ctx, channel_id, user_id, picker_page=picker_page)

    await safe_edit(
        callback,
        await at(user_id, "panel.channel_settings_text", title=title, id=channel_id),
        reply_markup=kb,
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:channel_reactions:(-?\d+)$"))
@safe_callback
async def on_channel_reactions(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    kb = await channel_reactions_kb(ctx, channel_id, user_id)
    await safe_edit(callback, await at(user_id, "panel.channel_reactions_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:channel_signature:(-?\d+)$"))
@safe_callback
async def on_channel_signature(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    kb = await channel_signature_kb(ctx, channel_id, user_id)
    await safe_edit(callback, await at(user_id, "panel.channel_signature_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:channel_watermark:(-?\d+)$"))
@safe_callback
async def on_channel_watermark(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:chs:(-?\d+)$"))
@safe_callback
async def on_channel_service_cleaner(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    kb = await service_cleaner_kb(
        ctx,
        channel_id,
        user_id=user_id,
        back_callback=f"panel:channel_settings:{channel_id}",
        types_callback=f"panel:chsp:{channel_id}:0",
        toggle_callback=f"panel:chsg:{channel_id}",
    )
    await safe_edit(callback, await at(user_id, "panel.service_cleaner_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:chsg:(-?\d+)$"))
@safe_callback
async def on_channel_service_cleaner_toggle_all(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    from src.db.repositories.chats import toggle_setting as toggle_ch_setting

    await toggle_ch_setting(ctx, channel_id, "cleanAllServices")

    kb = await service_cleaner_kb(
        ctx,
        channel_id,
        user_id=user_id,
        back_callback=f"panel:channel_settings:{channel_id}",
        types_callback=f"panel:chsp:{channel_id}:0",
        toggle_callback=f"panel:chsg:{channel_id}",
    )
    await safe_edit(callback, reply_markup=kb)
    await callback.answer(_plain(await at(user_id, "panel.setting_updated")))


@bot.on_callback_query(filters.regex(r"^panel:chsp:(-?\d+):(\d+)$"))
@safe_callback
async def on_channel_service_cleaner_types(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    kb = await service_cleaner_types_kb(
        ctx,
        channel_id,
        page,
        user_id=user_id,
        page_callback_prefix=f"panel:chsp:{channel_id}",
        toggle_callback_prefix=f"panel:chst:{channel_id}",
        back_callback=f"panel:chs:{channel_id}",
        toggle_mode="index",
    )
    total = math.ceil(len(get_available_service_types("channel")) / 10)
    text = await at(user_id, "panel.service_cleaner_types_text", page=page + 1, total=max(1, total))
    await safe_edit(callback, text, reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:chst:(-?\d+):(\d+):(\d+)$"))
@safe_callback
async def on_channel_service_cleaner_toggle_type(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))
    service_idx = int(callback.matches[0].group(2))
    page = int(callback.matches[0].group(3))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    settings = await get_chat_settings(ctx, channel_id)
    all_types = get_available_service_types(settings.chatType or "channel")
    if service_idx < 0 or service_idx >= len(all_types):
        await callback.answer(_plain(await at(user_id, "panel.error_generic")), show_alert=True)
        return

    service_type = all_types[service_idx]
    await toggle_service_type(ctx, channel_id, service_type)

    kb = await service_cleaner_types_kb(
        ctx,
        channel_id,
        page,
        user_id=user_id,
        page_callback_prefix=f"panel:chsp:{channel_id}",
        toggle_callback_prefix=f"panel:chst:{channel_id}",
        back_callback=f"panel:chs:{channel_id}",
        toggle_mode="index",
    )
    await safe_edit(callback, reply_markup=kb)

    label_key = f"panel.service_type_{service_type}"
    localized_type = await at(user_id, label_key)
    if localized_type == label_key:
        localized_type = service_type.replace("_", " ").title()
    await callback.answer(_plain(await at(user_id, "common.btn_action", type=localized_type)))


@bot.on_callback_query(filters.regex(r"^panel:toggle_ch:(\w+):(-?\d+)$"))
@safe_callback
async def on_channel_toggle_setting(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    field = callback.matches[0].group(1)
    channel_id = int(callback.matches[0].group(2))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    from src.db.repositories.chats import (
        get_chat_settings as get_ch_settings,
    )
    from src.db.repositories.chats import (
        toggle_setting as toggle_ch_setting,
    )
    from src.db.repositories.chats import (
        update_chat_setting as update_ch_setting,
    )

    if field == "reactionMode":
        s = await get_ch_settings(ctx, channel_id)
        new_mode = cycle_action(s.reactionMode, REACTION_MODES, default_action=ReactionMode.ALL)
        await update_ch_setting(ctx, channel_id, field, new_mode)
        kb = await channel_reactions_kb(ctx, channel_id, user_id)
    elif field == "reactionsEnabled":
        await toggle_ch_setting(ctx, channel_id, field)
        kb = await channel_reactions_kb(ctx, channel_id, user_id)
    elif field == "signatureEnabled":
        await toggle_ch_setting(ctx, channel_id, field)
        kb = await channel_signature_kb(ctx, channel_id, user_id)
    else:
        await toggle_ch_setting(ctx, channel_id, field)
        kb = await channel_settings_kb(ctx, channel_id, user_id)

    await safe_edit(callback, reply_markup=kb)
    await callback.answer(_plain(await at(user_id, "panel.setting_updated")))


@bot.on_callback_query(filters.regex(r"^panel:cycle_wm:(\w+):(-?\d+)$"))
@safe_callback
async def on_channel_cycle_watermark(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    mode = callback.matches[0].group(1)
    channel_id = int(callback.matches[0].group(2))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    from src.db.repositories.chats import get_chat_settings as get_ch_settings

    s = await get_ch_settings(ctx, channel_id)
    cfg = parse_watermark_config(s.watermarkText)

    if mode == "color":
        cfg.color = cycle_action(cfg.color, WATERMARK_COLORS, default_action=WatermarkColor.WHITE)
    elif mode == "video_quality":
        cfg.video_quality = cycle_action(
            cfg.video_quality, VIDEO_QUALITIES, default_action=VideoQuality.HIGH
        )
    elif mode == "video_motion":
        cfg.video_motion = cycle_action(
            cfg.video_motion, VIDEO_MOTIONS, default_action=VideoMotion.STATIC
        )
    elif mode == "position":
        cfg_pos = s.watermarkPosition or WatermarkPosition.BOTTOM_RIGHT
        new_pos = cycle_action(
            cfg_pos, WATERMARK_POSITIONS, default_action=WatermarkPosition.BOTTOM_RIGHT
        )
        await update_chat_setting(ctx, channel_id, "watermarkPosition", new_pos)
        await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
        await callback.answer()
        return
    else:
        cfg.style = cycle_action(
            cfg.style, WATERMARK_STYLES, default_action=WatermarkStyle.SOFT_SHADOW
        )

    await update_chat_setting(
        ctx,
        channel_id,
        "watermarkText",
        build_watermark_config(
            cfg.text,
            color=cfg.color,
            style=cfg.style,
            image_enabled=cfg.image_enabled,
            video_enabled=cfg.video_enabled,
            video_quality=cfg.video_quality,
            video_motion=cfg.video_motion,
        ),
    )
    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_wm_image:(-?\d+)$"))
@safe_callback
async def on_channel_toggle_wm_image(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    cfg = parse_watermark_config(s.watermarkText)
    cfg.image_enabled = not cfg.image_enabled

    await update_chat_setting(
        ctx,
        channel_id,
        "watermarkText",
        build_watermark_config(
            cfg.text,
            color=cfg.color,
            style=cfg.style,
            image_enabled=cfg.image_enabled,
            video_enabled=cfg.video_enabled,
            video_quality=cfg.video_quality,
            video_motion=cfg.video_motion,
        ),
    )
    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer(await at(user_id, "panel.setting_updated"))

    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer(await at(user_id, "panel.setting_updated"))


@bot.on_callback_query(filters.regex(r"^panel:toggle_wm_video:(-?\d+)$"))
@safe_callback
async def on_channel_toggle_wm_video(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    if not config.ENABLE_VIDEO_WATERMARK:
        await callback.answer(await at(user_id, "panel.wm_video_unavailable"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    cfg = parse_watermark_config(s.watermarkText)
    cfg.video_enabled = not cfg.video_enabled

    await update_chat_setting(
        ctx,
        channel_id,
        "watermarkText",
        build_watermark_config(
            cfg.text,
            color=cfg.color,
            style=cfg.style,
            image_enabled=cfg.image_enabled,
            video_enabled=cfg.video_enabled,
            video_quality=cfg.video_quality,
            video_motion=cfg.video_motion,
        ),
    )
    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer(await at(user_id, "panel.setting_updated"))


@bot.on_callback_query(filters.regex(r"^panel:clear_wm_text:(-?\d+)$"))
@safe_callback
async def on_channel_clear_watermark_text(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    cfg = parse_watermark_config(s.watermarkText)
    cfg.text = ""

    await update_chat_setting(
        ctx,
        channel_id,
        "watermarkText",
        build_watermark_config(
            cfg.text,
            color=cfg.color,
            style=cfg.style,
            image_enabled=cfg.image_enabled,
            video_enabled=cfg.video_enabled,
            video_quality=cfg.video_quality,
            video_motion=cfg.video_motion,
        ),
    )
    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer(_plain(await at(user_id, "panel.watermark_cleared")))


@bot.on_callback_query(filters.regex(r"^panel:clear_wm_image:(-?\d+)$"))
@safe_callback
async def on_channel_clear_watermark_image(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    await update_chat_setting(ctx, channel_id, "watermarkImage", None)
    await _render_channel_watermark_panel(callback, ctx, channel_id, user_id, user_id)
    await callback.answer(_plain(await at(user_id, "panel.setting_updated")))


@bot.on_callback_query(filters.regex(r"^panel:channel_buttons:(-?\d+)$"))
@safe_callback
async def on_channel_buttons(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    from src.plugins.admin_panel.handlers.keyboards import channel_buttons_kb

    s = await get_chat_settings(ctx, channel_id)
    buttons_raw = s.buttons or "[]"
    try:
        rows = json.loads(buttons_raw)
        btn_count = sum(len(row) for row in rows)
    except Exception:
        btn_count = 0

    text = await at(user_id, "panel.channel_buttons_text", count=btn_count)
    kb = await channel_buttons_kb(ctx, channel_id, user_id)

    await safe_edit(callback, text, reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:delete_ch_btn:(-?\d+):(\d+):(\d+)$"))
@safe_callback
async def on_channel_button_delete(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))
    row_idx = int(callback.matches[0].group(2))
    btn_idx = int(callback.matches[0].group(3))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    try:
        rows = json.loads(s.buttons or "[]")
        if 0 <= row_idx < len(rows) and 0 <= btn_idx < len(rows[row_idx]):
            rows[row_idx].pop(btn_idx)
            if not rows[row_idx]:
                rows.pop(row_idx)
            await update_chat_setting(ctx, channel_id, "buttons", json.dumps(rows))
    except Exception:
        pass

    from src.plugins.admin_panel.handlers.keyboards import channel_buttons_kb

    kb = await channel_buttons_kb(ctx, channel_id, user_id)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(await at(user_id, "panel.setting_updated"))


@bot.on_callback_query(filters.regex(r"^panel:cycle_ch_btn_style:(-?\d+):(\d+):(\d+)$"))
@safe_callback
async def on_channel_button_cycle_style(client: Client, callback: CallbackQuery):
    ctx = get_context()
    user_id = callback.from_user.id
    channel_id = int(callback.matches[0].group(1))
    row_idx = int(callback.matches[0].group(2))
    btn_idx = int(callback.matches[0].group(3))

    if not await is_admin(client, channel_id, user_id):
        await callback.answer(await at(user_id, "error.no_membership_admin"), show_alert=True)
        return

    s = await get_chat_settings(ctx, channel_id)
    try:
        rows = json.loads(s.buttons or "[]")
        if 0 <= row_idx < len(rows) and 0 <= btn_idx < len(rows[row_idx]):
            current_style = rows[row_idx][btn_idx].get("style", ButtonStyle.DEFAULT)
            new_style = cycle_action(
                current_style, BUTTON_STYLES, default_action=ButtonStyle.DEFAULT
            )
            rows[row_idx][btn_idx]["style"] = new_style
            await update_chat_setting(ctx, channel_id, "buttons", json.dumps(rows))
    except Exception:
        pass

    from src.plugins.admin_panel.handlers.keyboards import channel_buttons_kb

    kb = await channel_buttons_kb(ctx, channel_id, user_id)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()
