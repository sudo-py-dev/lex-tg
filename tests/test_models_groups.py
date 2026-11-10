import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.models import (
    AllowedChannel,
    ChatRules,
    ChatSettings,
    DisabledCommand,
)
from tests.factories import (
    AllowedChannelFactory,
    ChatCleanerFactory,
    ChatNightLockFactory,
    ChatRulesFactory,
    ChatSettingsFactory,
    DisabledCommandFactory,
)


@pytest.mark.asyncio
async def test_groupsettings_creation(db_session):
    gs = ChatSettingsFactory.build(id=-100, language="he")
    db_session.add(gs)
    await db_session.flush()

    result = await db_session.execute(select(ChatSettings).where(ChatSettings.id == -100))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.id == -100
    assert fetched.language == "he"


@pytest.mark.asyncio
async def test_groupsettings_duplicate_id(db_session):
    gs1 = ChatSettingsFactory.build(id=-111)
    db_session.add(gs1)
    await db_session.flush()
    db_session.expunge(gs1)

    gs2 = ChatSettingsFactory.build(id=-111)
    db_session.add(gs2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_grouprules_creation(db_session):
    rules = ChatRulesFactory.build(chatId=-200, content="No spam")
    db_session.add(rules)
    await db_session.flush()

    result = await db_session.execute(select(ChatRules).where(ChatRules.chatId == -200))
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.content == "No spam"


@pytest.mark.asyncio
async def test_grouprules_null_content(db_session):
    rules = ChatRulesFactory.build(chatId=-211, content=None)
    db_session.add(rules)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_groupcleaner_relationship(db_session):
    gs = ChatSettingsFactory.build(id=-300)
    db_session.add(gs)
    await db_session.flush()

    gc = ChatCleanerFactory.build(chatId=-300, cleanDeleted=True)
    db_session.add(gc)
    await db_session.flush()

    result = await db_session.execute(select(ChatSettings).where(ChatSettings.id == -300))
    fetched_gs = result.scalar_one()
    assert fetched_gs.ChatCleaner is not None
    assert fetched_gs.ChatCleaner.cleanDeleted is True
    assert fetched_gs.ChatCleaner.chatId == -300


@pytest.mark.asyncio
async def test_groupcleaner_fk_violation(db_session):
    gc = ChatCleanerFactory.build(chatId=999)  # Chat id 999 doesn't exist
    db_session.add(gc)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_nightlock_relationship(db_session):
    gs = ChatSettingsFactory.build(id=-400)
    db_session.add(gs)
    await db_session.flush()

    nl = ChatNightLockFactory.build(chatId=-400, isEnabled=True)
    db_session.add(nl)
    await db_session.flush()

    result = await db_session.execute(select(ChatSettings).where(ChatSettings.id == -400))
    fetched_gs = result.scalar_one()
    assert fetched_gs.nightLock is not None
    assert fetched_gs.nightLock.isEnabled is True
    assert fetched_gs.nightLock.chatId == -400


@pytest.mark.asyncio
async def test_nightlock_fk_violation(db_session):
    nl = ChatNightLockFactory.build(chatId=999)  # Chat id 999 doesn't exist
    db_session.add(nl)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_allowedchannel_creation(db_session):
    ac = AllowedChannelFactory.build(chatId=-500, channelId=123456)
    db_session.add(ac)
    await db_session.flush()

    result = await db_session.execute(select(AllowedChannel).where(AllowedChannel.chatId == -500))
    fetched = result.scalar_one()
    assert fetched.channelId == 123456


@pytest.mark.asyncio
async def test_disabledcommand_creation(db_session):
    dc = DisabledCommandFactory.build(chatId=-600, command="ban")
    db_session.add(dc)
    await db_session.flush()

    result = await db_session.execute(select(DisabledCommand).where(DisabledCommand.chatId == -600))
    fetched = result.scalar_one()
    assert fetched.command == "ban"
