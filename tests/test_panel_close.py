from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatType
from pyrogram.errors import MessageDeleteForbidden

from src.plugins.admin_panel.handlers.callbacks import user


@pytest.mark.parametrize("delete_allowed", [True, False])
async def test_panel_close_falls_back_when_delete_is_forbidden(delete_allowed):
    delete = AsyncMock(side_effect=None if delete_allowed else MessageDeleteForbidden())
    message = SimpleNamespace(
        id=308,
        chat=SimpleNamespace(type=ChatType.SUPERGROUP),
        delete=delete,
        edit_reply_markup=AsyncMock(),
    )
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123), message=message, answer=AsyncMock()
    )

    await user.on_panel_close(object(), callback)

    delete.assert_awaited_once()
    if delete_allowed:
        message.edit_reply_markup.assert_not_awaited()
    else:
        message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
    callback.answer.assert_awaited_once()
