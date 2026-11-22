from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from src.core.bot import bot
from src.core.context import AppContext, get_context
from src.utils.i18n import at
from src.utils.panel_session import bind_panel
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
    *,
    picker_page: int | None = None,
) -> None:
    """Send the main admin dashboard to a user in private chat."""
    ctx = get_context()
    from ..repository import get_chat_info

    chat_type, chat_title = await get_chat_info(ctx, chat_id)

    text, kb = await render_dashboard(
        ctx, chat_id, user_id if is_pm else None, chat_type, chat_title, text_key, picker_page
    )
    panel = await client.send_message(user_id, text, reply_markup=kb)
    if is_pm:
        await bind_panel(user_id, panel.id, chat_id, picker_page)


async def render_dashboard(
    ctx: AppContext,
    chat_id: int,
    user_id: int | None,
    chat_type: ChatType | str | None,
    chat_title: str | None,
    text_key: str | None = None,
    picker_page: int | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    options = {} if picker_page is None else {"picker_page": picker_page}
    if chat_type in (ChatType.CHANNEL, "channel"):
        from .keyboards import channel_settings_kb

        kb = await channel_settings_kb(ctx, chat_id, user_id or chat_id, **options)
        main_text_key = text_key or "panel.main_text_channel"
    else:
        kb = await main_menu_kb(chat_id, user_id, chat_type=chat_type, **options)
        main_text_key = text_key or "panel.main_text"
    return await at(user_id or chat_id, main_text_key, title=chat_title, id=chat_id), kb
