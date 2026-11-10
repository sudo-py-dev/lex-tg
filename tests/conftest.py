import asyncio
from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db import Base

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


_collection_loop: asyncio.AbstractEventLoop | None = None


def pytest_sessionstart(session):
    """Provide a loop for Telegram client imports during test collection."""
    global _collection_loop
    _collection_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_collection_loop)


def pytest_sessionfinish(session, exitstatus):
    if _collection_loop is not None:
        # Decorator imports enqueue handler registration on the collection loop.
        pending = asyncio.all_tasks(_collection_loop)
        if pending:
            _collection_loop.run_until_complete(asyncio.gather(*pending))
        _collection_loop.run_until_complete(_collection_loop.shutdown_asyncgens())
        _collection_loop.close()
    asyncio.set_event_loop(None)


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """Create a database engine for tests."""
    engine = create_async_engine(TEST_DATABASE_URL, future=True, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        # Create all tables defined in the Base metadata
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a clean database session for each test."""
    async_session = async_sessionmaker(
        bind=db_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )

    async with async_session() as session:
        yield session
        # Rollback any changes to keep the database clean for the next test
        await session.rollback()
