from pyrogram import Client, ContinuePropagation, filters
from pyrogram.types import CallbackQuery

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    _plain,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.moderation_kbs import (
    blacklist_defaults_kb,
    blacklist_kb,
    entityblock_kb,
    langblock_kb,
    logging_kb,
    slowmode_kb,
    stickers_kb,
    user_warns_kb,
    warns_kb,
)
from src.plugins.admin_panel.repository import get_chat_settings, update_chat_setting
from src.plugins.language import language_picker_kb
from src.utils.actions import (
    EXTENDED_MODERATION_ACTIONS,
    LANG_BLOCK_ACTIONS,
    MODERATION_ACTIONS,
    PUNISHMENT_ACTIONS,
    WARN_EXPIRY_OPTIONS,
    cycle_action,
)
from src.utils.i18n import at
from src.utils.permissions import Permission, check_user_permission


@bot.on_callback_query(filters.regex(r"^panel:langblock:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_langblock(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    kb = await langblock_kb(ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.langblock_picker_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:entityblock:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_entityblock(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    kb = await entityblock_kb(ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.entityblock_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:blacklist:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_blacklist(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    kb = await blacklist_kb(ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.blacklist_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:blacklist_remove:(\d+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_blacklist_remove(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    bid = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    async with ap_ctx.ctx.db() as session:
        from src.db.models import Blacklist

        obj = await session.get(Blacklist, bid)
        if obj and obj.chatId == chat_id:
            await session.delete(obj)
            await session.commit()
            from src.utils.message_rules import invalidate_rules

            await invalidate_rules("blacklist", chat_id)
            await callback.answer(_plain(await at(at_id, "panel.blacklist_removed_success")))
        else:
            await callback.answer(await at(at_id, "panel.blacklist_not_found"), show_alert=True)

    kb = await blacklist_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:cycle_blacklist_action:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_cycle_blacklist_action(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    page = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    settings = await get_chat_settings(ap_ctx.ctx, chat_id)

    nxt = cycle_action(settings.blacklistAction, MODERATION_ACTIONS, default_action="delete")

    async with ap_ctx.ctx.db() as session:
        from src.db.models import ChatSettings

        gs = await session.get(ChatSettings, chat_id)
        if gs:
            gs.blacklistAction = nxt
            session.add(gs)
            await session.commit()

    await callback.answer(
        await at(at_id, "panel.blacklist_action_set", action=await at(at_id, f"action.{nxt}")),
        show_alert=True,
    )
    kb = await blacklist_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_blacklist_buttons:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_toggle_blacklist_buttons(
    _: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext
):
    page = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    settings = await get_chat_settings(ap_ctx.ctx, chat_id)

    new_val = not settings.blacklistScanButtons

    await update_chat_setting(ap_ctx.ctx, chat_id, "blacklistScanButtons", new_val)
    await callback.answer(
        await at(
            at_id,
            "panel.blacklist_scan_buttons_updated",
            status=await at(at_id, "panel.status_enabled" if new_val else "panel.status_disabled"),
        ),
        show_alert=True,
    )

    kb = await blacklist_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:lang_toggle:(.*):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_lang_toggle(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    code = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    from src.plugins.lang_block import add_lang_block, get_lang_blocks, remove_lang_block
    from src.utils.lang_utils import get_lang_info

    config = await get_lang_blocks(ap_ctx.ctx, chat_id)
    blocks = set(config["blocked"])

    name, emoji_char = await get_lang_info(ap_ctx.ctx, code)
    display_name = f"{name} {emoji_char}"

    if code in blocks:
        await remove_lang_block(ap_ctx.ctx, chat_id, code)
        msg = await at(at_id, "panel.langblock_removed_item", lang=display_name)
    else:
        await add_lang_block(ap_ctx.ctx, chat_id, code)
        msg = await at(at_id, "panel.langblock_added_item", lang=display_name)

    kb = await langblock_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, reply_markup=kb)
    await callback.answer(msg)


@bot.on_callback_query(filters.regex(r"^panel:cycle_lang_block_action:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_cycle_lang_block_action(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    page = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    settings = await get_chat_settings(ap_ctx.ctx, chat_id)

    nxt = cycle_action(settings.langBlockAction, LANG_BLOCK_ACTIONS, default_action="delete")

    await update_chat_setting(ap_ctx.ctx, chat_id, "langBlockAction", nxt)

    # Invalidate config cache
    from src.plugins.lang_block import CACHE_KEY_PREFIX

    await ap_ctx.ctx.cache.delete(f"{CACHE_KEY_PREFIX}{chat_id}")

    await callback.answer(
        await at(at_id, "panel.langblock_action_set", action=await at(at_id, f"action.{nxt}")),
        show_alert=True,
    )
    kb = await language_picker_kb(
        ap_ctx.ctx, chat_id, page=page, mode="block", scope="chat", display_id=callback.from_user.id
    )
    await safe_edit(callback, reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:language:chat:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_chat_language(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    await safe_edit(
        callback,
        await at(at_id, "language.group_picker_header"),
        reply_markup=await language_picker_kb(
            ap_ctx.ctx, chat_id, scope="chat", page=page, display_id=callback.from_user.id
        ),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:language_page:(chat|user):(-?\d+):(\d+):(\w+)$"))
@admin_panel_context
@safe_callback
async def on_chat_language_page(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    scope = callback.matches[0].group(1)
    target_id = int(callback.matches[0].group(2))
    page = int(callback.matches[0].group(3))
    mode = callback.matches[0].group(4)
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, ap_ctx.chat_id)

    header_key = (
        "panel.langblock_picker_text" if mode == "block" else "language.group_picker_header"
    )

    await safe_edit(
        callback,
        await at(at_id, header_key),
        reply_markup=await language_picker_kb(
            ap_ctx.ctx,
            target_id,
            scope=scope,
            page=page,
            mode=mode,
            display_id=callback.from_user.id,
        ),
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:language_search:(chat|user):(-?\d+):(\w+)$"))
@admin_panel_context
@safe_callback
async def on_chat_language_search(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.plugins.language import begin_language_search

    user_id = callback.from_user.id
    scope = callback.matches[0].group(1)
    target_id = int(callback.matches[0].group(2))
    mode = callback.matches[0].group(3)
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, ap_ctx.chat_id)

    await begin_language_search(
        user_id, scope, target_id, prompt_msg_id=callback.message.id, mode=mode
    )
    await safe_edit(callback, await at(at_id, "language.search_prompt"))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:set_lang:chat:(-?\d+):([^:]+)(?::(.*))?$"))
@admin_panel_context
@safe_callback
async def on_chat_language_set(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.plugins.admin_panel.handlers.keyboards import settings_category_kb
    from src.plugins.language import set_chat_lang

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    new_lang = callback.matches[0].group(2)

    await set_chat_lang(ap_ctx.ctx, chat_id, new_lang)
    await callback.answer(_plain(await at(at_id, "panel.group_lang_set", lang=new_lang.upper())))

    chat_type_str = ap_ctx.chat_type.name.lower() if ap_ctx.chat_type else "supergroup"
    kb = await settings_category_kb(
        chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None, chat_type=chat_type_str
    )
    title_key = (
        "panel.general_text_channel" if chat_type_str == "channel" else "panel.settings_text"
    )
    await safe_edit(callback, await at(at_id, title_key), reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:warns$"))
@admin_panel_context
@safe_callback
async def on_warns_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    s = await get_chat_settings(ap_ctx.ctx, chat_id)
    kb = await warns_kb(
        ap_ctx.ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(
        callback,
        await at(
            at_id,
            "panel.warns_text",
            limit=s.warnLimit,
            action=await at(at_id, f"action.{s.warnAction.lower()}"),
            expiry=await at(at_id, f"expiry.{s.warnExpiry.lower()}"),
        ),
        reply_markup=kb,
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:slowmode$"))
@admin_panel_context
@safe_callback
async def on_slowmode_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.db.repositories.slowmode import get_slowmode

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    i = await get_slowmode(ap_ctx.ctx, chat_id)
    kb = await slowmode_kb(
        ap_ctx.ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.slowmode_text", interval=i), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:logging$"))
@admin_panel_context
@safe_callback
async def on_logging_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    s = await get_chat_settings(ap_ctx.ctx, chat_id)
    kb = await logging_kb(
        ap_ctx.ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(
        callback,
        await at(
            at_id,
            "panel.logging_text",
            channel=s.logChannelName or s.logChannelId or await at(at_id, "panel.not_set"),
        ),
        reply_markup=kb,
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:logging_picker(:(\d+))?$"))
@admin_panel_context
@safe_callback
async def on_logging_picker(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.plugins.admin_panel.handlers.moderation_kbs import log_channel_picker_kb
    from src.utils.local_cache import get_cache

    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id

    if not await check_user_permission(_, chat_id, user_id, Permission.CAN_BAN):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)

    kb = await log_channel_picker_kb(ap_ctx.ctx, chat_id, user_id=user_id if ap_ctx.is_pm else None)
    cache = get_cache()
    await cache.set(f"ap:logging_picker:{user_id}", chat_id, ttl=300)

    await _.send_message(
        user_id if ap_ctx.is_pm else callback.message.chat.id,
        await at(at_id, "panel.logging_picker_text"),
        reply_markup=kb,
    )
    await callback.message.delete()
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:logging_set:(-?\d+)$"))
@admin_panel_context
@safe_callback
async def on_logging_set(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    new_log_id = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    await update_chat_setting(ap_ctx.ctx, chat_id, "logChannelId", new_log_id)
    await callback.answer(_plain(await at(at_id, "panel.setting_updated")))

    s = await get_chat_settings(ap_ctx.ctx, chat_id)
    kb = await logging_kb(
        ap_ctx.ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_text(
        await at(
            at_id,
            "panel.logging_text",
            channel=s.logChannelName or s.logChannelId or await at(at_id, "panel.not_set"),
        ),
        reply_markup=kb,
    )


@bot.on_callback_query(filters.regex(r"^panel:logging_remove$"))
@admin_panel_context
@safe_callback
async def on_logging_remove(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    from src.plugins.admin_panel.repository import update_settings

    await update_settings(ap_ctx.ctx, chat_id, logChannelId=None, logChannelName=None)
    await callback.answer(_plain(await at(at_id, "panel.setting_updated")))

    s = await get_chat_settings(ap_ctx.ctx, chat_id)
    kb = await logging_kb(
        ap_ctx.ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_text(
        await at(
            at_id,
            "panel.logging_text",
            channel=s.logChannelName or s.logChannelId or await at(at_id, "panel.not_set"),
        ),
        reply_markup=kb,
    )


@bot.on_callback_query(filters.regex(r"^panel:cycle:(\w+)$"))
@admin_panel_context
@safe_callback
async def on_moderation_cycle(c: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        c, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    field = callback.matches[0].group(1)
    if field not in ("warnAction", "warnExpiry"):
        raise ContinuePropagation

    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    ctx = ap_ctx.ctx

    async with ctx.db() as session:
        s = await get_chat_settings(ctx, chat_id)

        current_warn_action = s.warnAction or "kick"
        current_warn_expiry = s.warnExpiry or "never"
        current_warn_limit = s.warnLimit or 3

        if field == "warnAction":
            nxt = cycle_action(current_warn_action, PUNISHMENT_ACTIONS, default_action="kick")
            s.warnAction = nxt
            session.add(s)
            await session.commit()
            kb = await warns_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await safe_edit(
                callback,
                await at(
                    at_id,
                    "panel.warns_text",
                    limit=current_warn_limit,
                    action=await at(at_id, f"action.{nxt}"),
                    expiry=await at(at_id, f"expiry.{current_warn_expiry.lower()}"),
                ),
                reply_markup=kb,
            )
        elif field == "warnExpiry":
            nxt = cycle_action(current_warn_expiry, WARN_EXPIRY_OPTIONS, default_action="never")
            s.warnExpiry = nxt
            session.add(s)
            await session.commit()
            kb = await warns_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await safe_edit(
                callback,
                await at(
                    at_id,
                    "panel.warns_text",
                    limit=current_warn_limit,
                    action=await at(at_id, f"action.{current_warn_action.lower()}"),
                    expiry=await at(at_id, f"expiry.{nxt}"),
                ),
                reply_markup=kb,
            )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_entity:(.*):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_toggle_entity(c: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        c, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    etype = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    ctx = ap_ctx.ctx

    from src.plugins.entity_block import (
        add_blocked_entity,
        get_blocked_entities,
        remove_blocked_entity,
    )

    blocks = await get_blocked_entities(ctx, chat_id)
    block = next((b for b in blocks if b.entityType == etype), None)

    if not block:
        await add_blocked_entity(ctx, chat_id, etype, "delete")
        next_action = "DELETE"
    else:
        nxt = cycle_action(block.action, EXTENDED_MODERATION_ACTIONS, default_action="delete")
        if nxt != "off":
            await add_blocked_entity(ctx, chat_id, etype, nxt)
            next_action = nxt.upper()
        else:
            await remove_blocked_entity(ctx, chat_id, etype)
            next_action = "OFF"

    res_msg = await at(at_id, "panel.entity_block_updated", type=etype.upper(), status=next_action)
    kb = await entityblock_kb(
        ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, reply_markup=kb)
    await callback.answer(res_msg)


@bot.on_callback_query(filters.regex(r"^panel:reset_warns$"))
@admin_panel_context
@safe_callback
async def on_reset_warns(c: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        c, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    from src.db.repositories.warns import reset_all_chat_warns

    await reset_all_chat_warns(ap_ctx.ctx, ap_ctx.chat_id)
    await callback.answer(
        _plain(
            await at(
                _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id),
                "panel.warns_reset_success",
            )
        ),
        show_alert=True,
    )


@bot.on_callback_query(filters.regex(r"^panel:user_warns:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_user_warns(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await user_warns_kb(
        ap_ctx.ctx, ap_ctx.chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.user_warns_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:user_warn_reset:(\d+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_user_warn_reset(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    target_uid = int(callback.matches[0].group(1))
    page = int(callback.matches[0].group(2))
    from src.db.repositories.warns import reset_warns

    await reset_warns(ap_ctx.ctx, ap_ctx.chat_id, target_uid)
    kb = await user_warns_kb(
        ap_ctx.ctx, ap_ctx.chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, reply_markup=kb)
    await callback.answer(
        _plain(
            await at(
                _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id),
                "panel.user_warns_reset_success",
            )
        )
    )


@bot.on_callback_query(filters.regex(r"^panel:user_warn_info:(\d+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_user_warn_info(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    target_uid = int(callback.matches[0].group(1))
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    from src.db.repositories.warns import get_warns

    warns = await get_warns(ap_ctx.ctx, ap_ctx.chat_id, target_uid)
    if not warns:
        await callback.answer(_plain(await at(at_id, "warns.no_warns")), show_alert=True)
        return
    reasons = "\n".join([f"- {w.reason or await at(at_id, 'common.no_reason')}" for w in warns])
    await callback.answer(
        f"{await at(at_id, 'common.user_id_label')} {target_uid}\n{await at(at_id, 'panel.user_warns_header')}\n{reasons}",
        show_alert=True,
    )


@bot.on_callback_query(filters.regex(r"^panel:blacklist_blocks:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_blacklist_blocks(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1))

    kb = await blacklist_defaults_kb(
        ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.blacklist_blocks_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:blacklist_inject:(low|medium|hard):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_blacklist_inject(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    level = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    user_id = callback.from_user.id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)

    from src.core.blacklist_defaults import BAD_WORDS_BLOCKS
    from src.db.repositories.blacklist import batch_add_blacklist

    patterns = BAD_WORDS_BLOCKS.get(level, [])
    added, skipped = await batch_add_blacklist(ap_ctx.ctx, chat_id, patterns)

    level_name = await at(at_id, f"common.level_{level}")

    if added > 0:
        msg = await at(at_id, "panel.blacklist_inject_success", count=added, level=level_name)
    else:
        msg = await at(at_id, "panel.blacklist_inject_error", success=added, failed=skipped)

    await callback.answer(msg, show_alert=True)

    kb = await blacklist_kb(ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.blacklist_text"), reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:stickers:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_stickers(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0

    kb = await stickers_kb(ap_ctx.ctx, chat_id, page, user_id=user_id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.stickers_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:cycle_sticker_action:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_cycle_sticker_action(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    page = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    settings = await get_chat_settings(ap_ctx.ctx, chat_id)

    nxt = cycle_action(
        settings.stickerAction or "delete",
        MODERATION_ACTIONS,
        default_action="delete",
    )

    await update_chat_setting(ap_ctx.ctx, chat_id, "stickerAction", nxt)

    await callback.answer(
        await at(at_id, "panel.setting_updated"),
        show_alert=True,
    )
    kb = await stickers_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:sticker_remove:(.*):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_sticker_remove(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    set_name = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    from src.db.repositories.stickers import remove_blocked_sticker_set

    await remove_blocked_sticker_set(ap_ctx.ctx, chat_id, set_name)
    await callback.answer(_plain(await at(at_id, "stickers.removed", set_name=set_name)))

    kb = await stickers_kb(
        ap_ctx.ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:sticker_noop:(\d+)$"))
@safe_callback
async def on_sticker_noop(_: Client, callback: CallbackQuery):
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:noop$"))
@safe_callback
async def on_noop(_: Client, callback: CallbackQuery):
    await callback.answer()
