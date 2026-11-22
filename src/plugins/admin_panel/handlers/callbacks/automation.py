from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.core.bot import bot
from src.db.models import ChatCleaner, ChatNightLock, ChatShabbatLock, Reminder
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    _panel_lang_id,
    _plain,
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import (
    chatnightlock_menu_kb,
    chatshabbatlock_menu_kb,
    cleaner_menu_kb,
    reminders_menu_kb,
    rules_kb,
    settings_category_kb,
    timezone_picker_kb,
    welcome_kb,
)
from src.plugins.admin_panel.handlers.service_cleaner import (
    service_cleaner_kb,
    service_cleaner_types_kb,
)
from src.plugins.admin_panel.repository import get_chat_settings, toggle_service_type
from src.utils.i18n import at
from src.utils.permissions import Permission, check_user_permission


@bot.on_callback_query(filters.regex(r"^panel:refresh_schedule$"))
@admin_panel_context
@safe_callback
async def on_refresh_schedule(client: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.plugins.scheduler.manager import SchedulerManager

    if not await check_user_permission(
        client, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return
    refreshed = await SchedulerManager.sync_group(ap_ctx.ctx, ap_ctx.chat_id)
    key = "panel.schedule_refreshed" if refreshed else "panel.schedule_refresh_failed"
    await callback.answer(await at(ap_ctx.at_id, key), show_alert=not refreshed)


@bot.on_callback_query(filters.regex(r"^panel:welcome$"))
@admin_panel_context
@safe_callback
async def on_welcome_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await welcome_kb(
        ap_ctx.ctx, ap_ctx.chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await safe_edit(callback, await at(at_id, "panel.welcome_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:rules$"))
@admin_panel_context
@safe_callback
async def on_rules_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await rules_kb(ap_ctx.chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None)
    await safe_edit(callback, await at(at_id, "panel.rules_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:reminders$"))
@admin_panel_context
@safe_callback
async def on_reminders_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await reminders_menu_kb(
        ap_ctx.ctx,
        ap_ctx.chat_id,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        back_callback="panel:category:automation",
    )
    await safe_edit(callback, await at(at_id, "panel.reminder_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:chatnightlock$"))
@admin_panel_context
@safe_callback
async def on_nightlock_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await chatnightlock_menu_kb(
        ap_ctx.ctx,
        ap_ctx.chat_id,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        back_callback="panel:category:automation",
    )
    await safe_edit(callback, await at(at_id, "panel.nightlock_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:chatshabbatlock$"))
@admin_panel_context
@safe_callback
async def on_shabbatlock_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, ap_ctx.chat_id)
    kb = await chatshabbatlock_menu_kb(
        ap_ctx.ctx,
        ap_ctx.chat_id,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        back_callback="panel:category:automation",
    )
    from src.plugins.admin_panel.repository import get_chat_settings

    settings = await get_chat_settings(ap_ctx.ctx, ap_ctx.chat_id)
    async with ap_ctx.ctx.db() as session:
        lock = await session.get(ChatShabbatLock, ap_ctx.chat_id)
        if not lock:
            lock = ChatShabbatLock(chatId=ap_ctx.chat_id)
            session.add(lock)
            await session.commit()

    status = await at(at_id, "panel.status_enabled" if lock.isEnabled else "panel.status_disabled")
    await safe_edit(
        callback,
        await at(at_id, "panel.shabbat_text", status=status, timezone=settings.timezone),
        reply_markup=kb,
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_chatshabbatlock$"))
@admin_panel_context
@safe_callback
async def on_toggle_shabbatlock(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    async with ctx.db() as session:
        lock = await session.get(ChatShabbatLock, chat_id)
        if lock:
            lock.isEnabled = not lock.isEnabled
            session.add(lock)
            await session.commit()
            from src.plugins.scheduler.manager import SchedulerManager

            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
            at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
            await callback.answer(_plain(await at(at_id, "panel.setting_updated")))

            kb = await chatshabbatlock_menu_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            settings = await get_chat_settings(ctx, chat_id)
            status = await at(
                at_id, "panel.status_enabled" if lock.isEnabled else "panel.status_disabled"
            )
            await safe_edit(
                callback,
                await at(at_id, "panel.shabbat_text", status=status, timezone=settings.timezone),
                reply_markup=kb,
            )
            await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:cleaner$"))
@admin_panel_context
@safe_callback
async def on_cleaner_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    ctx = ap_ctx.ctx
    kb = await cleaner_menu_kb(
        ctx,
        chat_id,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        back_callback="panel:category:automation",
    )
    async with ctx.db() as session:
        cleaner = await session.get(ChatCleaner, chat_id)
        if not cleaner:
            cleaner = ChatCleaner(chatId=chat_id)
            session.add(cleaner)
            await session.commit()
    s_del = await at(
        at_id, "panel.status_enabled" if cleaner.cleanDeleted else "panel.status_disabled"
    )
    s_fake = await at(
        at_id, "panel.status_enabled" if cleaner.cleanFake else "panel.status_disabled"
    )
    await safe_edit(
        callback,
        await at(
            at_id,
            "panel.cleaner_text",
            s_del=s_del,
            s_fake=s_fake,
            days=cleaner.cleanInactiveDays,
            time=cleaner.cleanerRunTime,
        ),
        reply_markup=kb,
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:toggle_reminder:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_toggle_reminder(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    rid = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    async with ctx.db() as session:
        rem = await session.get(Reminder, rid)
        if rem and rem.chatId == chat_id:
            rem.isActive = not rem.isActive
            session.add(rem)
            await session.commit()
            from src.plugins.scheduler.manager import SchedulerManager

            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
            await callback.answer(
                _plain(
                    await at(
                        _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
                        "panel.setting_updated",
                    )
                )
            )
            kb = await reminders_menu_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:delete_reminder:(\d+)$"))
@admin_panel_context
@safe_callback
async def on_delete_reminder(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    rid = int(callback.matches[0].group(1))
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    async with ctx.db() as session:
        rem = await session.get(Reminder, rid)
        if rem and rem.chatId == chat_id:
            await session.delete(rem)
            await session.commit()
            from src.plugins.scheduler.manager import SchedulerManager

            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
            await callback.answer(
                _plain(
                    await at(
                        _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
                        "panel.setting_updated",
                    )
                )
            )
            kb = await reminders_menu_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:toggle_chatnightlock$"))
@admin_panel_context
@safe_callback
async def on_toggle_nightlock(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    async with ctx.db() as session:
        lock = await session.get(ChatNightLock, chat_id)
        if lock:
            lock.isEnabled = not lock.isEnabled
            session.add(lock)
            await session.commit()
            from src.plugins.scheduler.manager import SchedulerManager

            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
            await callback.answer(
                _plain(
                    await at(
                        _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
                        "panel.setting_updated",
                    )
                )
            )
            kb = await chatnightlock_menu_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:toggle_cleaner:(\w+)$"))
@admin_panel_context
@safe_callback
async def on_toggle_cleaner(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    ctype = callback.matches[0].group(1)
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    async with ctx.db() as session:
        cleaner = await session.get(ChatCleaner, chat_id)
        if cleaner:
            if ctype == "deleted":
                cleaner.cleanDeleted = not cleaner.cleanDeleted
            elif ctype == "fake":
                cleaner.cleanFake = not cleaner.cleanFake
            session.add(cleaner)
            await session.commit()
            from src.plugins.scheduler.manager import SchedulerManager

            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
            await callback.answer(
                _plain(
                    await at(
                        _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
                        "panel.setting_updated",
                    )
                )
            )
            kb = await cleaner_menu_kb(
                ctx, chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None
            )
            await callback.message.edit_reply_markup(reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:timezone:?(\d+)?$"))
@admin_panel_context
@safe_callback
async def on_timezone_panel(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    page = int(callback.matches[0].group(1)) if callback.matches[0].group(1) else 0
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    ctx = ap_ctx.ctx

    settings = await get_chat_settings(ctx, chat_id)
    kb = await timezone_picker_kb(
        ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_text(
        await at(at_id, "panel.timezone_text", timezone=settings.timezone), reply_markup=kb
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:timezone_region:(\w+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_timezone_region(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    region = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    kb = await timezone_picker_kb(
        ap_ctx.ctx,
        chat_id,
        page,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        region=region,
    )
    await callback.message.edit_text(
        await at(at_id, "panel.timezone_region_text", region=region), reply_markup=kb
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:timezone_filter:(.*):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_timezone_filter(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    q = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    kb = await timezone_picker_kb(
        ap_ctx.ctx,
        chat_id,
        page,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        filter_query=q,
    )
    await callback.message.edit_text(
        await at(at_id, "panel.timezone_search_results_text", query=q), reply_markup=kb
    )
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:timezone_search$"))
@admin_panel_context
@safe_callback
async def on_timezone_search_prompt(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    from src.utils.input import capture_next_input

    user_id = callback.from_user.id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, ap_ctx.chat_id)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    await at(at_id, "common.btn_cancel"),
                    callback_data="panel:cancel_input:timezone",
                )
            ]
        ]
    )
    await safe_edit(callback, await at(at_id, "panel.timezone_search_prompt"), reply_markup=kb)
    await capture_next_input(user_id, ap_ctx.chat_id, "timezoneSearch", callback.message.id)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:set_tz:(.*)$"))
@admin_panel_context
@safe_callback
async def on_set_timezone(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    new_tz = callback.matches[0].group(1)
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    from src.db.models import ChatSettings
    from src.plugins.scheduler.manager import SchedulerManager

    async with ctx.db() as session:
        gs = await session.get(ChatSettings, chat_id)
        if gs:
            gs.timezone = new_tz
            session.add(gs)
            await session.commit()
            if not await SchedulerManager.sync_group(ctx, chat_id):
                await callback.answer(
                    await at(ap_ctx.at_id, "panel.schedule_refresh_failed"), show_alert=True
                )
                return
    await callback.answer(_plain(await at(at_id, "panel.timezone_set_success", tz=new_tz)))
    chat_type_str = ap_ctx.chat_type.name.lower() if ap_ctx.chat_type else "supergroup"
    kb = await settings_category_kb(
        chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None, chat_type=chat_type_str
    )
    title_key = "panel.general_text_channel" if chat_type_str == "channel" else "panel.general_text"
    await callback.message.edit_text(await at(at_id, title_key), reply_markup=kb)


@bot.on_callback_query(filters.regex(r"^panel:toggle_private_rules$"))
@admin_panel_context
@safe_callback
async def on_toggle_private_rules(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    from src.db.repositories.rules import get_rules, toggle_private_rules

    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    rules = await get_rules(ctx, chat_id)
    new_state = not (rules.privateMode if rules else False)
    await toggle_private_rules(ctx, chat_id, new_state)
    kb = await rules_kb(chat_id, user_id=callback.from_user.id if ap_ctx.is_pm else None)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(
        _plain(
            await at(
                _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id),
                "panel.setting_updated",
            )
        )
    )


@bot.on_callback_query(filters.regex(r"^panel:svc:(\w+)$"))
@admin_panel_context
@safe_callback
async def on_service_cleaner_main(_: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    ctx = ap_ctx.ctx
    nav_hint = callback.matches[0].group(1)

    kb = await service_cleaner_kb(
        ctx,
        chat_id,
        user_id=user_id if ap_ctx.is_pm else None,
        back_callback=f"panel:category:{nav_hint}",
        types_callback=f"panel:svc_types:0:{nav_hint}",
        toggle_callback=f"panel:svc_toggle:cleanAllServices:{nav_hint}",
    )
    await callback.message.edit_text(await at(at_id, "panel.service_cleaner_text"), reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:svc_toggle:(\w+):(\w+)$"))
@admin_panel_context
@safe_callback
async def on_service_cleaner_toggle_master(
    _: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext
):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    field = callback.matches[0].group(1)
    nav_hint = callback.matches[0].group(2)
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx

    from src.plugins.admin_panel.repository import toggle_setting

    await toggle_setting(ctx, chat_id, field)

    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)
    kb = await service_cleaner_kb(
        ctx,
        chat_id,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        back_callback=f"panel:category:{nav_hint}",
        types_callback=f"panel:svc_types:0:{nav_hint}",
        toggle_callback=f"panel:svc_toggle:cleanAllServices:{nav_hint}",
    )
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer(_plain(await at(at_id, "panel.setting_updated")))


@bot.on_callback_query(filters.regex(r"^panel:svc_types:(\d+):(\w+)$"))
@admin_panel_context
@safe_callback
async def on_service_cleaner_view_types(
    _: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext
):
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    page = int(callback.matches[0].group(1))
    nav_hint = callback.matches[0].group(2)
    at_id = _panel_lang_id(ap_ctx.is_pm, user_id, chat_id)
    ctx = ap_ctx.ctx

    kb = await service_cleaner_types_kb(
        ctx,
        chat_id,
        page,
        user_id=user_id if ap_ctx.is_pm else None,
        page_callback_prefix="panel:svc_types",  # Note: logic in Types KB will need hint
        toggle_callback_prefix=f"panel:svc_type_toggle:{nav_hint}",
        back_callback=f"panel:svc:{nav_hint}",
    )

    from src.db.repositories.chats import get_chat_settings
    from src.plugins.admin_panel.handlers.service_cleaner import get_available_service_types

    settings = await get_chat_settings(ctx, chat_id)
    total = __import__("math").ceil(
        len(get_available_service_types(settings.chatType or "supergroup")) / 10
    )

    # Manually fix pagination to include hint
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data.startswith("panel:svc_types:"):
                btn.callback_data += f":{nav_hint}"

    text = await at(at_id, "panel.service_cleaner_types_text", page=page + 1, total=max(1, total))
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:svc_type_toggle:(\w+):(\w+):(\d+)$"))
@admin_panel_context
@safe_callback
async def on_service_cleaner_toggle_type(
    _: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext
):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    nav_hint = callback.matches[0].group(1)
    service_type = callback.matches[0].group(2)
    page = int(callback.matches[0].group(3))
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx

    from src.plugins.admin_panel.repository import toggle_service_type

    await toggle_service_type(ctx, chat_id, service_type)

    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    kb = await service_cleaner_types_kb(
        ctx,
        chat_id,
        page,
        user_id=callback.from_user.id if ap_ctx.is_pm else None,
        page_callback_prefix="panel:svc_types",
        toggle_callback_prefix=f"panel:svc_type_toggle:{nav_hint}",
        back_callback=f"panel:svc:{nav_hint}",
    )
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data.startswith("panel:svc_types:"):
                btn.callback_data += f":{nav_hint}"

    await callback.message.edit_reply_markup(reply_markup=kb)

    label_key = f"panel.service_type_{service_type}"
    localized_type = await at(at_id, label_key)
    if localized_type == label_key:
        localized_type = service_type.replace("_", " ").title()
    await callback.answer(_plain(await at(at_id, "common.btn_action", type=localized_type)))


@admin_panel_context
@safe_callback
async def on_toggle_service_type_general(
    _: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext
):
    if not await check_user_permission(
        _, ap_ctx.chat_id, callback.from_user.id, Permission.CAN_BAN
    ):
        await callback.answer(await at(ap_ctx.at_id, "error.admin_no_permission"), show_alert=True)
        return

    service_type = callback.matches[0].group(1)
    page = int(callback.matches[0].group(2))
    chat_id = ap_ctx.chat_id
    ctx = ap_ctx.ctx
    at_id = _panel_lang_id(ap_ctx.is_pm, callback.from_user.id, chat_id)

    await toggle_service_type(ctx, chat_id, service_type)
    kb = await service_cleaner_types_kb(
        ctx, chat_id, page, user_id=callback.from_user.id if ap_ctx.is_pm else None
    )
    await callback.message.edit_reply_markup(reply_markup=kb)
    label_key = f"panel.service_type_{service_type}"
    localized_type = await at(at_id, label_key)
    if localized_type == label_key:
        localized_type = service_type.replace("_", " ").title()
    await callback.answer(_plain(await at(at_id, "common.btn_action", type=localized_type)))
