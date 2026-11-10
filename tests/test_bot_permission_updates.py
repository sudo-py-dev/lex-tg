import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram import ContinuePropagation, raw
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import ChannelPrivate, UserNotParticipant
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.db.models import ChatAdmin
from src.db.repositories.chats import get_chat_settings
from src.plugins import admin_sync
from src.utils.admin_cache import Permission, has_permission
from src.utils.local_cache import AsyncSnapshotCache


@pytest.fixture
async def permission_state(db_engine, mocker):
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    cache = AsyncSnapshotCache()
    mocker.patch.object(admin_sync, "get_context", return_value=ctx)
    mocker.patch.object(admin_sync, "get_cache", return_value=cache)
    mocker.patch("src.utils.admin_cache.get_context", return_value=ctx)
    mocker.patch("src.utils.admin_cache.get_cache", return_value=cache)
    client = SimpleNamespace(me=SimpleNamespace(id=99, first_name="Bot", username="bot"))
    chat = SimpleNamespace(id=-10012345, title="Channel", type=ChatType.CHANNEL)
    return ctx, cache, client, chat


async def test_channel_permission_changes_and_demotion(permission_state):
    ctx, cache, client, chat = permission_state
    for status, privileges, active in [
        (ChatMemberStatus.ADMINISTRATOR, {"can_post_messages": True}, True),
        (
            ChatMemberStatus.ADMINISTRATOR,
            {"can_post_messages": False, "can_edit_messages": True},
            True,
        ),
        (ChatMemberStatus.MEMBER, None, True),
        (ChatMemberStatus.LEFT, None, False),
    ]:
        member = SimpleNamespace(
            status=status, privileges=SimpleNamespace(**privileges) if privileges else None
        )
        await admin_sync.refresh_bot_permissions(client, chat, member)
        settings = await get_chat_settings(ctx, chat.id)
        assert settings.chatType == "channel"
        assert settings.isActive == active
        assert json.loads(settings.botPrivileges) == (privileges or {})
        assert await has_permission(client, chat.id, Permission.CAN_POST) == bool(
            privileges and privileges.get("can_post_messages")
        )
        async with ctx.db() as session:
            admin = await session.get(ChatAdmin, (chat.id, client.me.id))
            assert bool(admin) == (status == ChatMemberStatus.ADMINISTRATOR)
        # A cache miss must not resurrect old permissions from the database.
        await cache.delete(f"bot_privs:{chat.id}")
        assert await has_permission(client, chat.id, Permission.CAN_POST) == bool(
            privileges and privileges.get("can_post_messages")
        )


async def test_member_update_without_privileges_revokes_rights(permission_state):
    _, cache, client, chat = permission_state
    await cache.setex(f"bot_privs:{chat.id}", 3600, {"can_post_messages": True})
    old = SimpleNamespace(user=client.me, status=ChatMemberStatus.ADMINISTRATOR)
    new = SimpleNamespace(user=client.me, status=ChatMemberStatus.MEMBER, privileges=None)
    update = SimpleNamespace(chat=chat, old_chat_member=old, new_chat_member=new, from_user=None)
    with pytest.raises(ContinuePropagation):
        await admin_sync.on_chat_member_updated(client, update)
    assert not await has_permission(client, chat.id, Permission.CAN_POST)


@pytest.mark.parametrize("removed", [None, UserNotParticipant, ChannelPrivate])
async def test_raw_channel_update_refreshes_own_rights(permission_state, removed):
    _, _, client, chat = permission_state
    client.get_chat = AsyncMock(return_value=chat)
    client.get_chat_member = AsyncMock(
        return_value=SimpleNamespace(
            status=ChatMemberStatus.ADMINISTRATOR,
            privileges=SimpleNamespace(can_post_messages=True),
        )
    )
    if removed == UserNotParticipant:
        client.get_chat_member.side_effect = UserNotParticipant()
    elif removed == ChannelPrivate:
        client.get_chat.side_effect = ChannelPrivate()
    with pytest.raises(ContinuePropagation):
        await admin_sync.on_channel_permissions_changed(
            client, raw.types.UpdateChannel(channel_id=12345), {}, {}
        )
    assert await has_permission(client, chat.id, Permission.CAN_POST) == (removed is None)


async def test_unrelated_raw_update_does_not_query_telegram(mocker):
    client = SimpleNamespace(get_chat=AsyncMock())
    with pytest.raises(ContinuePropagation):
        await admin_sync.on_channel_permissions_changed(client, object(), {}, {})
    client.get_chat.assert_not_awaited()
