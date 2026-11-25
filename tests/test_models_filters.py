import pytest
from sqlalchemy import select

from src.core.context import AppContext
from src.db.models import Filter
from src.db.repositories.filters import (
    add_filter,
    get_filters_count,
    get_filters_paginated,
    remove_all_filters,
    remove_filter_by_id,
)
from src.utils.local_cache import AsyncSnapshotCache
from tests.factories import ChatSettingsFactory


@pytest.fixture
def app_context(db_engine):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    session_factory = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False
    )
    return AppContext(db=session_factory, cache=AsyncSnapshotCache(), scheduler=AsyncIOScheduler())


@pytest.mark.asyncio
async def test_filter_creation(db_session, app_context):
    gs = ChatSettingsFactory.build(id=-100)
    db_session.add(gs)
    await db_session.flush()

    f = await add_filter(app_context, -100, "hello", "hi there")
    assert f.keyword == "hello"
    assert f.text == "hi there"
    assert f.chatId == -100


@pytest.mark.asyncio
async def test_filter_with_settings(db_session, app_context):
    gs = ChatSettingsFactory.build(id=-500)
    db_session.add(gs)
    await db_session.flush()

    settings = {"isAdminOnly": True, "isSilent": True}
    f = await add_filter(app_context, -500, "secret", "shhh", settings=settings)
    assert f.settings["isAdminOnly"] is True
    assert f.settings["isSilent"] is True


@pytest.mark.asyncio
async def test_filter_pagination(db_session, app_context):
    chat_id = -200
    gs = ChatSettingsFactory.build(id=chat_id)
    db_session.add(gs)
    await db_session.flush()

    # Add 15 filters
    for i in range(1, 16):
        await add_filter(app_context, chat_id, f"kw{i:02d}", f"resp{i}")

    # Test count
    count = await get_filters_count(app_context, chat_id)
    assert count == 15

    # Test page 0 (size 10)
    page0 = await get_filters_paginated(app_context, chat_id, 0, 10)
    assert len(page0) == 10
    assert page0[0].keyword == "kw01"
    assert page0[-1].keyword == "kw10"

    # Test page 1 (size 10)
    page1 = await get_filters_paginated(app_context, chat_id, 1, 10)
    assert len(page1) == 5
    assert page1[0].keyword == "kw11"
    assert page1[-1].keyword == "kw15"


@pytest.mark.asyncio
async def test_remove_filter_by_id(db_session, app_context):
    chat_id = -300
    gs = ChatSettingsFactory.build(id=chat_id)
    db_session.add(gs)
    await db_session.flush()

    f = await add_filter(app_context, chat_id, "test", "resp")
    f_id = f.id

    success = await remove_filter_by_id(app_context, f_id, chat_id=chat_id)
    assert success is True

    # Verify deleted
    result = await db_session.execute(select(Filter).where(Filter.id == f_id))
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_remove_all_filters(db_session, app_context):
    chat_id = -400
    gs = ChatSettingsFactory.build(id=chat_id)
    db_session.add(gs)
    await db_session.flush()

    await add_filter(app_context, chat_id, "kw1", "r1")
    await add_filter(app_context, chat_id, "kw2", "r2")

    count = await remove_all_filters(app_context, chat_id)
    assert count == 2

    new_count = await get_filters_count(app_context, chat_id)
    assert new_count == 0
