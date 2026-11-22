from pyrogram.types import InlineKeyboardButton


async def get_pager(
    current_page: int, total_count: int, page_size: int, callback_prefix: str
) -> list[InlineKeyboardButton]:
    """Reusable pagination row for the admin panel."""
    nav_row = []
    if current_page > 0:
        nav_row.append(
            InlineKeyboardButton("⬅️", callback_data=f"{callback_prefix}:{current_page - 1}")
        )

    total_pages = (total_count + page_size - 1) // page_size
    if total_pages > 1:
        nav_row.append(
            InlineKeyboardButton(f"{current_page + 1} / {total_pages}", callback_data="panel:noop")
        )

    if (current_page + 1) * page_size < total_count:
        nav_row.append(
            InlineKeyboardButton("➡️", callback_data=f"{callback_prefix}:{current_page + 1}")
        )
    return nav_row
