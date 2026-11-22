from src.utils.local_cache import get_cache


async def bind_panel(
    user_id: int, message_id: int, chat_id: int, picker_page: int | None = None
) -> None:
    """Associate a private Telegram message with its settings target."""
    await get_cache().set(f"panel_target:{user_id}:{message_id}", (chat_id, picker_page), ttl=86400)


async def get_panel_session(user_id: int, message_id: int) -> tuple[int | None, int | None]:
    return await get_cache().get(f"panel_target:{user_id}:{message_id}") or (None, None)
