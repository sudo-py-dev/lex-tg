from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.core.bot import bot
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.repository import get_chat_settings, update_chat_setting
from src.plugins.admin_panel.validation import is_setting_allowed
from src.utils.actions import FLOOD_ACTIONS, MODERATION_ACTIONS, PUNISHMENT_ACTIONS
from src.utils.i18n import at
from src.utils.permissions import Permission, can_manage_blacklist, check_user_permission

from .common import safe_callback, safe_edit
from .moderation import on_blacklist, on_warns_panel
from .security import on_flood_panel

_ACTIONS = {
    "blacklistAction": MODERATION_ACTIONS,
    "floodAction": FLOOD_ACTIONS,
    "warnAction": PUNISHMENT_ACTIONS,
}


@bot.on_callback_query(
    filters.regex(r"^panel:action:(blacklistAction|floodAction|warnAction):(\d+)(?::(\w+))?$")
)
@admin_panel_context
@safe_callback
async def on_action_picker(client: Client, callback: CallbackQuery, panel: AdminPanelContext):
    field, page_str, choice = callback.matches[0].groups()
    page = int(page_str)
    chat_type = panel.chat_type.name.lower() if panel.chat_type else "supergroup"
    can_manage = (
        await can_manage_blacklist(client, panel.chat_id, callback.from_user.id)
        if field == "blacklistAction"
        else await check_user_permission(
            client, panel.chat_id, callback.from_user.id, Permission.CAN_BAN
        )
    )
    if not is_setting_allowed(field, chat_type) or not can_manage:
        await callback.answer(await at(panel.at_id, "error.admin_no_permission"), show_alert=True)
        return

    options = _ACTIONS[field]
    routes = {
        "blacklistAction": f"panel:blacklist:{page}",
        "floodAction": "panel:flood",
        "warnAction": "panel:warns",
    }
    if choice is not None:
        if choice not in options:
            await callback.answer(await at(panel.at_id, "panel.error_generic"), show_alert=True)
            return
        await update_chat_setting(panel.ctx, panel.chat_id, field, choice)
        if field == "blacklistAction":
            await on_blacklist(client, callback, panel, page=page)
        elif field == "floodAction":
            await on_flood_panel(client, callback, panel)
        else:
            await on_warns_panel(client, callback, panel)
        return

    settings = await get_chat_settings(panel.ctx, panel.chat_id)
    current = getattr(settings, field)
    buttons = []
    for action in options:
        label = await at(panel.at_id, f"action.{action}")
        if current == action:
            label = f"✓ {label}"
        buttons.append(
            [InlineKeyboardButton(label, callback_data=f"panel:action:{field}:{page}:{action}")]
        )
    buttons.append(
        [InlineKeyboardButton(await at(panel.at_id, "panel.btn_back"), callback_data=routes[field])]
    )
    await safe_edit(
        callback,
        await at(panel.at_id, "panel.choose_action"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    await callback.answer()
