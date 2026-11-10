from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models import (
    ActionLog,
    SudoUser,
    TimedAction,
    UserConnection,
)
from tests.factories import (
    ActionLogFactory,
    SudoUserFactory,
    TimedActionFactory,
    UserConnectionFactory,
)


@pytest.mark.asyncio
async def test_sudouser_creation(db_session):
    sudo_user = SudoUserFactory.build(userId=123, addedBy=456)
    db_session.add(sudo_user)
    await db_session.flush()

    result = await db_session.execute(select(SudoUser).where(SudoUser.userId == 123))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.userId == 123
    assert fetched.addedBy == 456
    assert isinstance(fetched.createdAt, datetime)


@pytest.mark.asyncio
async def test_sudouser_unique_userId(db_session):
    sudo1 = SudoUserFactory.build(userId=777)
    db_session.add(sudo1)
    await db_session.flush()
    db_session.expunge(sudo1)

    sudo2 = SudoUserFactory.build(userId=777)
    db_session.add(sudo2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_userconnection_creation(db_session):
    conn = UserConnectionFactory.build(userId=222, activeChatId=-100)
    db_session.add(conn)
    await db_session.flush()

    result = await db_session.execute(select(UserConnection).where(UserConnection.userId == 222))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.userId == 222
    assert fetched.activeChatId == -100


@pytest.mark.asyncio
async def test_actionlog_creation(db_session):
    log = ActionLogFactory.build(
        chatId=-100, actorId=111, targetId=222, action="ban", reason="spam"
    )
    db_session.add(log)
    await db_session.flush()

    result = await db_session.execute(select(ActionLog).where(ActionLog.chatId == -100))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.actorId == 111
    assert fetched.action == "ban"


@pytest.mark.asyncio
async def test_actionlog_null_action(db_session):
    log = ActionLogFactory.build(chatId=-111, action=None)
    db_session.add(log)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_timedaction_creation(db_session):
    exp = datetime.now(UTC) + timedelta(hours=1)
    ta = TimedActionFactory.build(chatId=-100, userId=333, action="mute", expiresAt=exp)
    db_session.add(ta)
    await db_session.flush()

    result = await db_session.execute(select(TimedAction).where(TimedAction.userId == 333))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.action == "mute"


@pytest.mark.asyncio
async def test_userconnection_unique_userId(db_session):
    # First user connection
    conn1 = UserConnectionFactory.build(userId=444)
    db_session.add(conn1)
    await db_session.flush()

    # Second user connection with same userId should fail
    conn2 = UserConnectionFactory.build(userId=444)
    db_session.add(conn2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_timestamp_mixin_behavior(db_session):
    # ActionLog doesn't use TimestampMixin but SudoUser has createdAt
    # Let's test UserConnection which uses TimestampMixin
    conn = UserConnectionFactory.build()
    db_session.add(conn)
    await db_session.flush()

    assert conn.createdAt is not None
    assert conn.updatedAt is not None

    initial_updated_at = conn.updatedAt

    # Wait a bit and modify
    conn.activeChatId = -500
    db_session.add(conn)
    await db_session.flush()

    assert conn.updatedAt >= initial_updated_at
