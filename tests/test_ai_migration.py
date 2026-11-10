import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from src.db import Base
from src.db.models import AIConversationTurn


async def test_additive_conversation_migration_preserves_existing_tables(db_engine):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/b27a619d08e1_add_ai_conversation_turns.py"
    )
    spec = importlib.util.spec_from_file_location("ai_turn_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def round_trip(connection):
        AIConversationTurn.__table__.drop(connection)
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "aiconversationturn" in inspect(connection).get_table_names()
            assert len(inspect(connection).get_indexes("aiconversationturn")) == 2
            migration.downgrade()
            assert "aiconversationturn" not in inspect(connection).get_table_names()
        assert "chatsettings" in inspect(connection).get_table_names()
        # Production startup's create_all also adds the table without altering old tables.
        Base.metadata.create_all(connection)
        assert "aiconversationturn" in inspect(connection).get_table_names()

    async with db_engine.begin() as connection:
        await connection.run_sync(round_trip)
