from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.bot import bot
from src.core.context import get_context
from src.utils.i18n import at
from src.utils.permissions import is_admin

from ..decorators import AdminPanelContext, admin_panel_context
from ..repository import resolve_chat_type, set_active_chat
from .keyboards import main_menu_kb, my_groups_kb


@bot.on_message(filters.command("settings"))
@admin_panel_context
async def settings_handler(client: Client, message: Message, ap_ctx: AdminPanelContext) -> None:
    if not ap_ctx.is_pm:
        import asyncio

        from src.utils.admin_cache import sync_admins_from_telegram

        asyncio.create_task(sync_admins_from_telegram(client, ap_ctx.chat_id))

        me = await client.get_me()
        url = f"https://t.me/{me.username}?start=settings_{ap_ctx.chat_id}"
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton(await at(ap_ctx.chat_id, "panel.btn_manage_pm"), url=url)]]
        )
        await message.reply(await at(ap_ctx.chat_id, "panel.redirect_pm_text"), reply_markup=kb)
        return

    await open_settings_panel(client, message, ap_ctx.chat_id, chat_type=ap_ctx.chat_type)


async def open_settings_panel(
    client: Client, message: Message, chat_id: int, chat_type: ChatType | str | None = None
) -> None:
    ctx = get_context()
    is_pm = message.chat.type == ChatType.PRIVATE
    # Onboarding callbacks pass the bot-authored language picker message.
    user_id = message.chat.id if is_pm else message.from_user.id

    if chat_id >= 0 or not await is_admin(client, chat_id, user_id):
        await message.reply(await at(user_id, "panel.error_not_admin"))
        if is_pm:
            kb = await my_groups_kb(ctx, client, user_id)
            await message.reply(await at(user_id, "panel.my_groups_title"), reply_markup=kb)
        return

    if is_pm:
        if not chat_type:
            chat_type = await resolve_chat_type(ctx, chat_id)
        chat_type_str = chat_type if isinstance(chat_type, str) else chat_type.name.lower()
        await set_active_chat(ctx, user_id, chat_id, chat_type=chat_type_str)

    await send_admin_dashboard(client, user_id, chat_id, chat_type=chat_type, is_pm=is_pm)


async def send_admin_dashboard(
    client: Client,
    user_id: int,
    chat_id: int,
    chat_type: ChatType | str | None = None,
    is_pm: bool = True,
    text_key: str | None = None,
) -> None:
    """Send the main admin dashboard to a user in private chat."""
    ctx = get_context()
    from ..repository import get_chat_info

    chat_type_obj, chat_title = await get_chat_info(ctx, chat_id)
    if not chat_type:
        chat_type = chat_type_obj

    if chat_type == ChatType.CHANNEL or chat_type == "channel":
        from .keyboards import channel_settings_kb

        kb = await channel_settings_kb(ctx, chat_id, user_id if is_pm else None)
        main_text_key = text_key or "panel.main_text_channel"
    else:
        kb = await main_menu_kb(chat_id, user_id if is_pm else None, chat_type=chat_type)
        main_text_key = text_key or "panel.main_text"

    await client.send_message(
        user_id,
        await at(user_id if is_pm else chat_id, main_text_key, title=chat_title),
        reply_markup=kb,
    )
