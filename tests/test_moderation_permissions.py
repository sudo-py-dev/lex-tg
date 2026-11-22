from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.config import config
from src.db.models import FedAdmin, SudoUser
from src.db.repositories.gban import add_sudo, is_sudo
from src.plugins.federation import create_fed, fban_user, is_fbanned, join_fed


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
