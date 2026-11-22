from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from src.core.bot import bot
from src.db.repositories.admins import get_admins_for_chat
from src.plugins.admin_panel.decorators import AdminPanelContext, admin_panel_context
from src.plugins.admin_panel.handlers.callbacks.common import (
    safe_callback,
    safe_edit,
)
from src.plugins.admin_panel.handlers.keyboards import admins_management_kb
from src.utils.admin_cache import force_refresh, get_chat_admins
from src.utils.i18n import at
from src.utils.local_cache import get_cache


async def render_admin_roster(
    callback: CallbackQuery, ap_ctx: AdminPanelContext, page: int = 0
) -> None:
    user_id = callback.from_user.id
    chat_id = ap_ctx.chat_id
    at_id = ap_ctx.at_id
    admins = await get_admins_for_chat(ap_ctx.ctx, chat_id)
    last_sync = await get_cache().get(f"admins_last_sync:{chat_id}")
    date = last_sync or await at(at_id, "panel.not_set")
    text = await at(at_id, "panel.admins_mgmt_text", title=ap_ctx.chat_title, date=date)
    text = text.replace("**", "").replace("`", "")
    page_size = 12
    page = min(page, max(0, (len(admins) - 1) // page_size))
    admins.sort(key=lambda admin: (admin.status != "owner", admin.userId))
    rows = []
    for admin in admins[page * page_size : (page + 1) * page_size]:
        name = f"@{admin.username}" if admin.username else admin.firstName or str(admin.userId)
        role = await at(at_id, f"panel.admin_role_{admin.status}")
        rows.append(f"• \u2068{name}\u2069 · {role}")
    if not rows:
        rows.append(await at(at_id, "panel.admin_roster_empty"))

    await safe_edit(
        callback,
        "\n\n".join((text, "\n".join(rows))),
        reply_markup=await admins_management_kb(chat_id, user_id, page, len(admins), page_size),
        parse_mode=ParseMode.DISABLED,
    )


@bot.on_callback_query(filters.regex(r"^panel:admins_mgmt(?::(\d+))?$"))
@admin_panel_context
@safe_callback
async def on_admins_management(client: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    await get_chat_admins(client, ap_ctx.chat_id)
    await render_admin_roster(callback, ap_ctx, int(callback.matches[0].group(1) or 0))
    await callback.answer()


@bot.on_callback_query(filters.regex(r"^panel:admins_refresh:(-?\d+)(?::(\d+))?$"))
@admin_panel_context
@safe_callback
async def on_admins_refresh(client: Client, callback: CallbackQuery, ap_ctx: AdminPanelContext):
    chat_id = int(callback.matches[0].group(1))
    at_id = ap_ctx.at_id
    if chat_id != ap_ctx.chat_id:
        await callback.answer(await at(at_id, "common.err_access_denied"), show_alert=True)
        return

    cache = get_cache()
    cooldown_key = f"refresh_admins_cooldown:{chat_id}"
    if await cache.exists(cooldown_key):
        await callback.answer(await at(at_id, "panel.error_refresh_cooldown"), show_alert=True)
        return

    if not await force_refresh(client, chat_id):
        await callback.answer(await at(at_id, "panel.admin_refresh_failed"), show_alert=True)
        return

    await cache.set(cooldown_key, True, ttl=3600)
    await render_admin_roster(callback, ap_ctx, int(callback.matches[0].group(2) or 0))
    await callback.answer(await at(at_id, "panel.admin_refresh_success"))
