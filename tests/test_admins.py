import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pyrogram.enums import ChatMemberStatus

from src.db.models.chats import ChatAdmin, ChatSettings
from src.utils.admin_cache import is_admin, sync_admins_from_telegram
from src.utils.permissions import Permission, check_user_permission


class MockAsyncContextManager:
    def __init__(self, obj):
        self.obj = obj

    async def __aenter__(self):
        return self.obj

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def mock_context(db_session, mocker):
    mock_ctx = mocker.Mock()
    mock_ctx.db.return_value = MockAsyncContextManager(db_session)
    return mock_ctx


@pytest.mark.asyncio
async def test_sync_admins_from_telegram(db_session, mock_context, mocker):
    """Test that sync_admins_from_telegram correctly populates DB and cache."""
    client = MagicMock()
    client.me.id = 999  # Mock bot ID

    member = MagicMock()
    member.user.id = 123
    member.user.first_name = "TestUser"
    member.user.username = "testuser"
    member.status = ChatMemberStatus.ADMINISTRATOR
    member.privileges = MagicMock()
    member.privileges.can_restrict_members = True

    async def mock_members(*args, **kwargs):
        yield member

    client.get_chat_members.return_value = mock_members()

    chat_id = -1001

    # Create ChatSettings to satisfy FK constraint
    settings = ChatSettings(id=chat_id, isActive=True)
    db_session.add(settings)
    await db_session.commit()

    with patch("src.utils.admin_cache.get_context", return_value=mock_context):
        from src.utils.local_cache import AsyncSnapshotCache

        mock_cache = AsyncSnapshotCache()
        with patch("src.utils.admin_cache.get_cache", return_value=mock_cache):
            admin_ids = await sync_admins_from_telegram(client, chat_id)
            assert 123 in admin_ids

            # Verify DB persistence
            admin = await db_session.get(ChatAdmin, (chat_id, 123))
            assert admin is not None
            assert admin.status == "administrator"


@pytest.mark.asyncio
async def test_is_admin_tiers(db_session, mock_context, mocker):
    """Test the 3-tier is_admin logic (Cache -> DB -> API)."""
    client = MagicMock()
    client.me.id = 111  # Mock bot ID
    chat_id = -500
    user_id = 999

    # Create ChatSettings
    settings = ChatSettings(id=chat_id, isActive=True)
    db_session.add(settings)
    await db_session.commit()

    from src.utils.local_cache import AsyncSnapshotCache

    mock_cache = AsyncSnapshotCache()

    with (
        patch("src.utils.admin_cache.get_cache", return_value=mock_cache),
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
    ):
        member = MagicMock()
        member.user.id = user_id
        member.user.first_name = "AdminUser"
        member.user.username = "adminuser"
        member.status = ChatMemberStatus.ADMINISTRATOR

        async def mock_members(*args, **kwargs):
            yield member

        client.get_chat_members.return_value = mock_members()

        # Tier 3 -> API (Populates DB and Cache)
        assert await is_admin(client, chat_id, user_id) is True

        # Tier 1 -> Cache
        client.get_chat_members.reset_mock()
        assert await is_admin(client, chat_id, user_id) is True
        assert not client.get_chat_members.called

        # Tier 2 -> DB (expire cache list but keep DB)
        from src.core.constants import CacheKeys

        await mock_cache.delete(CacheKeys.admins(chat_id))

        # Should still be True because of DB (already populated by Tier 3)
        assert await is_admin(client, chat_id, user_id) is True
        assert not client.get_chat_members.called


@pytest.mark.asyncio
async def test_check_user_permission(db_session, mock_context, mocker):
    """Test granular permission checking."""
    client = MagicMock()
    chat_id = -700
    user_id = 888

    # Create ChatSettings
    settings = ChatSettings(
        id=chat_id, isActive=True, lastAdminsUpdate=datetime.now(UTC).replace(tzinfo=None)
    )
    db_session.add(settings)
    await db_session.commit()

    from src.utils.local_cache import AsyncSnapshotCache

    mock_cache = AsyncSnapshotCache()

    with (
        patch("src.utils.admin_cache.get_cache", return_value=mock_cache),
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
    ):
        # Manual insertion to avoid triggers
        admin = ChatAdmin(
            chatId=chat_id,
            userId=user_id,
            status="administrator",
            firstName="PermUser",
            privileges=json.dumps({"can_restrict_members": True}),
        )
        db_session.add(admin)
        await db_session.commit()

        # Check permission (should hit DB)
        assert await check_user_permission(client, chat_id, user_id, Permission.CAN_BAN) is True
        assert (
            await check_user_permission(client, chat_id, user_id, Permission.CAN_PROMOTE) is False
        )

        # Verify it cached the result
        cached = await mock_cache.get(f"admin_detail:{chat_id}:{user_id}")
        assert isinstance(cached, dict)
        assert cached["can_restrict_members"] is True


@pytest.mark.asyncio
async def test_get_chat_admins(db_session, mock_context, mocker):
    """Test that get_chat_admins follows tiers and returns correct IDs."""
    client = MagicMock()
    client.me.id = 111  # Mock bot ID
    chat_id = -999
    user_id = 777

    # Create ChatSettings
    settings = ChatSettings(id=chat_id, isActive=True)
    db_session.add(settings)
    await db_session.commit()

    from src.utils.local_cache import AsyncSnapshotCache

    mock_cache = AsyncSnapshotCache()

    with (
        patch("src.utils.admin_cache.get_cache", return_value=mock_cache),
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
    ):
        member = MagicMock()
        member.user.id = user_id
        member.user.first_name = "TargetAdmin"
        member.user.username = "targetadmin"
        member.status = ChatMemberStatus.ADMINISTRATOR

        async def mock_members(*args, **kwargs):
            yield member

        client.get_chat_members.return_value = mock_members()

        from src.utils.admin_cache import get_chat_admins

        # Call get_chat_admins
        ids = await get_chat_admins(client, chat_id)
        assert user_id in ids
        assert len(ids) == 1

        # Verify it cached
        from src.core.constants import CacheKeys

        cached = await mock_cache.get(CacheKeys.admins(chat_id))
        assert user_id in json.loads(cached)


@pytest.mark.asyncio
async def test_bot_permission_persistence(db_session, mock_context, mocker):
    """Test that bot privileges are persisted to ChatSettings during sync."""
    client = MagicMock()
    chat_id = -1234
    bot_id = 111
    client.me.id = bot_id

    # Create ChatSettings
    settings = ChatSettings(id=chat_id, isActive=True)
    db_session.add(settings)
    await db_session.commit()

    member = MagicMock()
    member.user.id = bot_id
    member.user.first_name = "BotUser"
    member.user.username = "botuser"
    member.status = ChatMemberStatus.ADMINISTRATOR
    member.privileges = MagicMock()
    member.privileges.can_restrict_members = True
    member.privileges.can_delete_messages = False

    async def mock_members(*args, **kwargs):
        yield member

    client.get_chat_members.return_value = mock_members()

    from src.utils.local_cache import AsyncSnapshotCache

    mock_cache = AsyncSnapshotCache()

    with (
        patch("src.utils.admin_cache.get_cache", return_value=mock_cache),
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
    ):
        await sync_admins_from_telegram(client, chat_id)

        # Verify DB persistence in ChatSettings
        await db_session.refresh(settings)
        assert settings.botPrivileges is not None
        privs = json.loads(settings.botPrivileges)
        assert privs["can_restrict_members"] is True
        assert privs["can_delete_messages"] is False

        # Verify bot_privs cache
        cached_privs = await mock_cache.get(f"bot_privs:{chat_id}")
        assert cached_privs["can_restrict_members"] is True

        # Test has_permission uses this
        from src.utils.admin_cache import has_permission

        with patch("src.db.repositories.chats.get_chat_settings", return_value=settings):
            assert await has_permission(client, chat_id, Permission.CAN_BAN) is True
            assert await has_permission(client, chat_id, Permission.CAN_DELETE) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("partial", [False, True])
async def test_failed_admin_sync_preserves_groups(db_session, mock_context, partial):
    from src.core.constants import CacheKeys
    from src.db.repositories.chats import get_user_admin_chats
    from src.utils.local_cache import AsyncSnapshotCache

    chat_id, user_id = -12345, 123
    db_session.add(ChatSettings(id=chat_id, title="Saved group", isActive=True))
    await db_session.commit()
    db_session.add(ChatAdmin(chatId=chat_id, userId=user_id, status="owner", firstName="Owner"))
    await db_session.commit()
    cache = AsyncSnapshotCache()
    await cache.set(CacheKeys.admins(chat_id), json.dumps([user_id]))
    await cache.set(f"admin_detail:{chat_id}:{user_id}", "owner")
    client = MagicMock()
    member = MagicMock()
    member.user.id = 456
    member.user.first_name = "New admin"
    member.user.username = None
    member.status = ChatMemberStatus.ADMINISTRATOR
    member.privileges = None

    async def failing_members(*args, **kwargs):
        if partial:
            yield member
        raise RuntimeError("Telegram temporarily unavailable")

    client.get_chat_members.side_effect = failing_members
    with (
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
        patch("src.utils.admin_cache.get_cache", return_value=cache),
    ):
        await sync_admins_from_telegram(client, chat_id, force=True)

    assert await db_session.get(ChatAdmin, (chat_id, user_id)) is not None
    assert await db_session.get(ChatAdmin, (chat_id, 456)) is None
    assert await get_user_admin_chats(mock_context, client, user_id) == [(chat_id, "Saved group")]
    assert await cache.get(f"admin_detail:{chat_id}:{user_id}") == "owner"
    assert await cache.get(CacheKeys.admins(chat_id)) == json.dumps([user_id])
    assert not await cache.exists(f"admin_sync_cooldown:{chat_id}")


@pytest.mark.asyncio
async def test_successful_sync_removes_old_privileges(db_session, mock_context):
    from src.utils.local_cache import AsyncSnapshotCache

    chat_id, removed_id = -54321, 123
    db_session.add(ChatSettings(id=chat_id, isActive=True))
    await db_session.commit()
    db_session.add(ChatAdmin(chatId=chat_id, userId=removed_id, status="owner", firstName="Old"))
    await db_session.commit()
    cache = AsyncSnapshotCache()
    await cache.set(f"admin_detail:{chat_id}:{removed_id}", "owner")
    client = MagicMock()
    member = MagicMock()
    member.user.id = 456
    member.user.first_name = "New owner"
    member.user.username = None
    member.status = ChatMemberStatus.OWNER
    member.privileges = None

    async def members(*args, **kwargs):
        yield member

    client.get_chat_members.side_effect = members
    with (
        patch("src.utils.admin_cache.get_context", return_value=mock_context),
        patch("src.utils.admin_cache.get_cache", return_value=cache),
    ):
        assert await sync_admins_from_telegram(client, chat_id, force=True) == {456}
    db_session.expire_all()
    assert await db_session.get(ChatAdmin, (chat_id, removed_id)) is None
    assert await db_session.get(ChatAdmin, (chat_id, 456)) is not None
    assert await cache.get(f"admin_detail:{chat_id}:{removed_id}") is None
    assert await cache.get(f"admin_detail:{chat_id}:456") == "owner"


@pytest.mark.asyncio
async def test_admin_snapshot_commit_failure_preserves_previous_list(
    db_session, mock_context, mocker
):
    from src.db.repositories.admins import replace_chat_admins

    chat_id = -76543
    db_session.add(ChatSettings(id=chat_id, isActive=True))
    await db_session.commit()
    db_session.add(ChatAdmin(chatId=chat_id, userId=123, status="owner", firstName="Original"))
    await db_session.commit()
    commit = mocker.patch.object(db_session, "commit", side_effect=RuntimeError("Commit failed"))
    with pytest.raises(RuntimeError, match="Commit failed"):
        await replace_chat_admins(
            mock_context,
            chat_id,
            [ChatAdmin(chatId=chat_id, userId=456, status="owner", firstName="Replacement")],
        )
    commit.assert_awaited_once()
    assert await db_session.get(ChatAdmin, (chat_id, 123)) is not None
    assert await db_session.get(ChatAdmin, (chat_id, 456)) is None
