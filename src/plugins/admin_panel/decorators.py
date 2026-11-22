from __future__ import annotations

import contextlib
import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, Message

from src.core.context import AppContext, get_context
from src.utils.i18n import at
from src.utils.panel_session import get_panel_session
from src.utils.permissions import is_admin

from .repository import get_active_chat, get_chat_info


@dataclass
class AdminPanelContext:
    chat_id: int
    at_id: int
    ctx: AppContext
    is_pm: bool
    chat_type: ChatType | None = None
    chat_title: str | None = None
    picker_page: int | None = None


def admin_panel_context(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """
    Decorator for admin panel handlers (Messages or Callbacks).
    Resolves the target chat_id (connected chat in PM or current chat in Group)
    and verifies admin permissions.
    """

    @functools.wraps(func)
    async def wrapper(
        client: Client, event: Message | CallbackQuery, *args: Any, **kwargs: Any
    ) -> None:
        if isinstance(event, CallbackQuery):
            logger.debug(f"Admin Panel Callback Received: {event.data} from {event.from_user.id}")

        # Check if ap_ctx is already provided (e.g. internal redirection)
        if any(isinstance(arg, AdminPanelContext) for arg in args) or "ap_ctx" in kwargs:
            return await func(client, event, *args, **kwargs)

        user_id = event.from_user.id
        is_pm = False

        message = event if isinstance(event, Message) else event.message
        if message and message.chat.type == ChatType.PRIVATE:
            is_pm = True

        ctx = get_context()

        picker_page = None
        if not is_pm:
            chat_id = message.chat.id
            chat_type, chat_title = await get_chat_info(ctx, chat_id, refresh=False)
        else:
            if isinstance(event, CallbackQuery):
                chat_id, picker_page = await get_panel_session(user_id, message.id)
                chat_type_str = None
            else:
                chat_id, chat_type_str = await get_active_chat(ctx, user_id)
            if not chat_id:
                logger.debug(f"Admin Panel: NO ACTIVE CONNECTION found for user {user_id} in PM.")
                from .handlers.keyboards import my_chats_menu_kb

                kb = await my_chats_menu_kb(user_id)
                text = await at(user_id, "panel.pick_group")
                if isinstance(event, CallbackQuery):
                    with contextlib.suppress(MessageNotModified):
                        await event.message.edit_text(text, reply_markup=kb)
                    await event.answer()
                else:
                    await event.reply(text, reply_markup=kb)
                return

            # Resolve type and title
            logger.debug(f"Admin Panel: Resolving chat info for {chat_id}...")
            chat_type_obj, chat_title = await get_chat_info(ctx, chat_id, refresh=False)
            chat_type = chat_type_obj

            # If the stored type was missing or changed, update it in the DB session/connection
            chat_type_name = chat_type.name.lower()
            if isinstance(event, Message) and chat_type_str != chat_type_name:
                from .repository import set_active_chat as update_conn

                await update_conn(ctx, user_id, chat_id, chat_type=chat_type_name)

        at_id = user_id if is_pm else chat_id
        if not await is_admin(client, chat_id, user_id):
            logger.debug(f"Admin Panel: User {user_id} REJECTED (Not Admin) for chat {chat_id}")
            if is_pm:
                from .handlers.keyboards import my_chats_menu_kb

                kb = await my_chats_menu_kb(user_id)
                text = await at(user_id, "common.err_access_denied")
                if isinstance(event, CallbackQuery):
                    await event.message.edit_text(text, reply_markup=kb)
                    await event.answer()
                else:
                    await event.reply(text, reply_markup=kb)
            else:
                text = await at(at_id, "panel.error_not_admin")
                if isinstance(event, CallbackQuery):
                    await event.answer(text, show_alert=True)
                else:
                    await event.reply(text)
            return

        ap_ctx = AdminPanelContext(
            chat_id=chat_id,
            at_id=at_id,
            ctx=ctx,
            is_pm=is_pm,
            chat_type=chat_type,
            chat_title=chat_title,
            picker_page=picker_page,
        )

        await func(client, event, ap_ctx, *args, **kwargs)

    return wrapper
