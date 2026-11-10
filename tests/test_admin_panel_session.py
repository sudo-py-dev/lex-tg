from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatType

from src.plugins.admin_panel.handlers import commands


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_id", [-42, -10012345])
async def test_admin_panel_remembers_private_user(mocker, chat_id):
    ctx = object()
    mocker.patch.object(commands, "get_context", return_value=ctx)
    mocker.patch.object(
        commands, "resolve_chat_type", new_callable=AsyncMock, return_value=ChatType.GROUP
    )
    check = mocker.patch.object(commands, "is_admin", new_callable=AsyncMock, return_value=True)
    save = mocker.patch.object(commands, "set_active_chat", new_callable=AsyncMock)
    dashboard = mocker.patch.object(commands, "send_admin_dashboard", new_callable=AsyncMock)
    # Bot-authored messages appear when opening settings after language selection.
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123, type=ChatType.PRIVATE),
        from_user=SimpleNamespace(id=999),
    )
    client = object()
    await commands.open_settings_panel(client, message, chat_id, chat_type="channel")
    check.assert_awaited_once_with(client, chat_id, 123)
    save.assert_awaited_once_with(ctx, 123, chat_id, chat_type="group")
    dashboard.assert_awaited_once_with(client, 123, chat_id, chat_type=ChatType.GROUP, is_pm=True)


@pytest.mark.asyncio
async def test_rejected_group_does_not_replace_connection(mocker):
    mocker.patch.object(commands, "get_context")
    mocker.patch.object(commands, "is_admin", new_callable=AsyncMock, return_value=False)
    mocker.patch.object(commands, "at", new_callable=AsyncMock, return_value="Denied")
    mocker.patch.object(commands, "my_groups_kb", new_callable=AsyncMock)
    save = mocker.patch.object(commands, "set_active_chat", new_callable=AsyncMock)
    dashboard = mocker.patch.object(commands, "send_admin_dashboard", new_callable=AsyncMock)
    message = SimpleNamespace(
        chat=SimpleNamespace(id=123, type=ChatType.PRIVATE), reply=AsyncMock()
    )
    await commands.open_settings_panel(object(), message, -10012345)
    save.assert_not_awaited()
    dashboard.assert_not_awaited()


@pytest.mark.asyncio
async def test_active_group_survives_new_database_sessions(db_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from src.plugins.connections import get_active_chat, set_active_chat

    first_ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    await set_active_chat(first_ctx, 123, -42, chat_type="group")
    new_ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    assert await get_active_chat(new_ctx, 123) == (-42, "group")
    assert await get_active_chat(new_ctx, 456) == (None, None)
