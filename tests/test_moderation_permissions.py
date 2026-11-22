from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import Forbidden
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import config
from src.db.models import FedAdmin, SudoUser
from src.db.repositories.gban import add_sudo, is_sudo
from src.plugins import blacklist
from src.plugins.federation import create_fed, fban_user, is_fbanned, join_fed
from src.utils import decorators


async def test_only_bot_owner_can_authorize_sudo(db_engine, monkeypatch):
    monkeypatch.setattr(config, "OWNER_ID", 1)
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    async with ctx.db() as session:
        session.add(SudoUser(userId=3, addedBy=2))
        await session.commit()
    assert not await is_sudo(ctx, 3)
    with pytest.raises(PermissionError):
        await add_sudo(ctx, user_id=3, added_by=2)
    await add_sudo(ctx, user_id=3, added_by=1)
    assert await is_sudo(ctx, 3)


async def test_federation_join_and_ban_require_federation_authority(db_engine):
    ctx = SimpleNamespace(db=async_sessionmaker(db_engine, expire_on_commit=False))
    fed = await create_fed(ctx, "Test federation", owner_id=1)
    assert await join_fed(ctx, fed.id, -42, actor_id=2) is None
    assert await join_fed(ctx, fed.id, -42, actor_id=1) is not None
    assert await fban_user(ctx, -42, 3, "test", by=2) is None
    assert not await is_fbanned(ctx, fed.id, 3)
    assert await fban_user(ctx, -42, 3, "test", by=1) is not None
    async with ctx.db() as session:
        session.add(FedAdmin(fedId=fed.id, userId=2))
        await session.commit()
    assert await fban_user(ctx, -42, 4, "test", by=2) is not None
    assert await is_fbanned(ctx, fed.id, 4)


@pytest.mark.parametrize(
    ("handler", "repository_method"),
    [("add_blacklist_handler", "add_blacklist"), ("rm_blacklist_handler", "remove_blacklist")],
)
@pytest.mark.parametrize("rights", ["granted", "revoked", "unavailable"])
async def test_blacklist_commands_check_current_ban_rights(
    mocker, handler, repository_method, rights
):
    mocker.patch.object(decorators, "is_admin", return_value=True)
    mocker.patch.object(decorators, "check_user_permission", return_value=True)
    mocker.patch.object(blacklist, "at", side_effect=lambda _, key, **kwargs: key)
    mocker.patch.object(blacklist, "get_context")
    write = mocker.patch.object(blacklist, repository_method, return_value=True)
    member = SimpleNamespace(
        status=ChatMemberStatus.ADMINISTRATOR,
        privileges=SimpleNamespace(can_restrict_members=rights == "granted"),
    )
    client = SimpleNamespace(
        get_chat_member=AsyncMock(
            return_value=member, side_effect=Forbidden if rights == "unavailable" else None
        )
    )
    message = SimpleNamespace(
        chat=SimpleNamespace(id=-10042, type=ChatType.SUPERGROUP),
        from_user=SimpleNamespace(id=2),
        command=["command", "pattern"],
        text="/command pattern",
        reply=AsyncMock(),
    )

    await getattr(blacklist, handler)(client, message)

    client.get_chat_member.assert_awaited_once_with(-10042, 2)
    if rights == "granted":
        write.assert_awaited_once()
    else:
        write.assert_not_awaited()
        message.reply.assert_awaited_once_with("error.admin_no_permission")
