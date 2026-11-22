from src.core.context import AppContext
from src.db.repositories.chats import (
    get_chat_info,
    get_chat_settings,
    get_user_admin_chat_page,
    get_user_admin_chats,
    resolve_chat_type,
    set_chat_active_status,
    toggle_service_type,
    toggle_setting,
    update_chat_setting,
    update_settings,
)

__all__ = [
    "get_chat_info",
    "get_chat_settings",
    "get_user_admin_chat_page",
    "get_user_admin_chats",
    "resolve_chat_type",
    "set_chat_active_status",
    "toggle_service_type",
    "toggle_setting",
    "update_chat_setting",
    "update_settings",
    "get_active_chat",
    "set_active_chat",
]


async def get_active_chat(ctx: AppContext, user_id: int) -> tuple[int | None, str | None]:
    """Get the currently connected group and its type for a user in PM."""
    from src.plugins.connections import get_active_chat as get_connected_chat

    return await get_connected_chat(ctx, user_id)


async def set_active_chat(
    ctx: AppContext, user_id: int, chat_id: int, chat_type: str | None = None
) -> None:
    """Set the active group connection and its type for a user in PM."""
    from src.plugins.connections import set_active_chat as set_connected_chat

    await set_connected_chat(ctx, user_id, chat_id, chat_type=chat_type)
