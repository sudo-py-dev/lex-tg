from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatType
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.core.bot import bot
from src.db.models import ChatAdmin, ChatSettings
from src.db.repositories.chats import get_chat_info, get_chat_settings, get_user_admin_chats
from src.plugins import admin_sync
from src.plugins.admin_panel.handlers import commands
from src.plugins.admin_panel.handlers.callbacks import user


@pytest.mark.parametrize(
    ("telegram_type", "expected"),
    [
        (ChatType.GROUP, "group"),
        (ChatType.SUPERGROUP, "supergroup"),
        (ChatType.FORUM, "supergroup"),
        (ChatType.CHANNEL, "channel"),
    ],
)
async def test_identity_and_resolution_repair_chat_type(db_engine, mocker, telegram_type, expected):
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    chat_id = -10012345
    async with ctx.db() as session:
        session.add(
            ChatSettings(id=chat_id, title="Saved title", chatType="channel", isActive=True)
        )
        await session.commit()
        session.add(ChatAdmin(chatId=chat_id, userId=123, status="owner"))
        await session.commit()
    chat = SimpleNamespace(id=chat_id, type=telegram_type, title="Group title", linked_chat_id=None)
    mocker.patch.object(bot, "get_chat", new_callable=AsyncMock, return_value=chat)
    chat_type, title = await get_chat_info(ctx, chat_id)
    assert chat_type.name.lower() == expected
    assert title == "Group title"
    assert (await get_chat_settings(ctx, chat_id)).chatType == expected

    # Message registration must preserve the same classification as API resolution.
    mocker.patch.object(admin_sync, "_REGISTERED_CHATS", set())
    await admin_sync.ensure_chat_identity(ctx, chat)
    assert (await get_chat_settings(ctx, chat_id)).chatType == expected
    for types, should_include in [
        ([ChatType.GROUP, ChatType.SUPERGROUP], expected != "channel"),
        ([ChatType.CHANNEL], expected == "channel"),
    ]:
        chats = await get_user_admin_chats(ctx, bot, 123, chat_type=types)
        assert bool(chats) == should_include


async def test_stale_channel_button_opens_group_panel(mocker):
    mocker.patch.object(user, "get_context", return_value=object())
    mocker.patch("src.utils.admin_cache.is_admin", new_callable=AsyncMock, return_value=True)
    mocker.patch.object(
        user, "get_chat_info", new_callable=AsyncMock, return_value=(ChatType.SUPERGROUP, "Group")
    )
    group_panel = mocker.patch.object(user, "on_select_chat", new_callable=AsyncMock)
    save = mocker.patch.object(user, "set_active_chat", new_callable=AsyncMock)
    callback = SimpleNamespace(
        from_user=SimpleNamespace(id=123), matches=[SimpleNamespace(group=lambda _: "-10012345")]
    )
    await user.on_select_channel(object(), callback)
    group_panel.assert_awaited_once()
    save.assert_not_awaited()


async def test_dashboard_ignores_stale_channel_hint(mocker):
    mocker.patch.object(commands, "get_context", return_value=object())
    mocker.patch(
        "src.plugins.admin_panel.repository.get_chat_info",
        new_callable=AsyncMock,
        return_value=(ChatType.SUPERGROUP, "Group"),
    )
    group_menu = mocker.patch.object(commands, "main_menu_kb", new_callable=AsyncMock)
    channel_menu = mocker.patch(
        "src.plugins.admin_panel.handlers.keyboards.channel_settings_kb", new_callable=AsyncMock
    )
    mocker.patch.object(commands, "at", new_callable=AsyncMock, return_value="Dashboard")
    client = SimpleNamespace(send_message=AsyncMock())
    await commands.send_admin_dashboard(client, 123, -10012345, chat_type="channel")
    group_menu.assert_awaited_once_with(-10012345, 123, chat_type=ChatType.SUPERGROUP)
    channel_menu.assert_not_awaited()
