"""Run with python -m scripts.benchmark_message_rules; never touches production data."""

import asyncio
import json
import re
import statistics
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.db import Base
from src.db.models import Blacklist, ChatSettings, Filter
from src.db.repositories.blacklist import get_all_blacklist
from src.db.repositories.chats import get_chat_settings
from src.db.repositories.filters import get_all_filters
from src.utils.message_rules import (
    get_block_rules,
    get_block_settings,
    get_reply_rules,
    invalidate_rules,
    match_block,
)


async def benchmark(messages: int = 300) -> dict:
    with tempfile.TemporaryDirectory(prefix="lex-message-benchmark-") as directory:
        engine = create_async_engine(f"sqlite+aiosqlite:///{Path(directory) / 'bench.sqlite3'}")
        ctx = SimpleNamespace(db=async_sessionmaker(engine, expire_on_commit=False))
        chat_id = -987654321
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            async with ctx.db() as session:
                session.add(ChatSettings(id=chat_id))
                await session.commit()
                session.add_all(
                    [
                        Blacklist(
                            chatId=chat_id, pattern=f"blocked{i}", isRegex=False, isWildcard=False
                        )
                        for i in range(200)
                    ]
                    + [
                        Filter(chatId=chat_id, keyword=f"keyword{i}", text="reply", settings={})
                        for i in range(200)
                    ]
                )
                await session.commit()
            queries = 0

            def count_queries(*args):
                nonlocal queries
                queries += 1

            event.listen(engine.sync_engine, "before_cursor_execute", count_queries)
            text = "An ordinary message without any configured matching words."

            async def previous_path():
                blocks = await get_all_blacklist(ctx, chat_id)
                await get_chat_settings(ctx, chat_id)
                for block in blocks:
                    re.search(block.pattern, text.lower(), re.I)
                replies = await get_all_filters(ctx, chat_id)
                for rule in replies:
                    re.search(rf"\b{re.escape(rule.keyword.lower())}\b", text.lower())

            async def cached_path():
                match_block(await get_block_rules(ctx, chat_id), text)
                await get_block_settings(ctx, chat_id)
                for rule in await get_reply_rules(ctx, chat_id):
                    rule.matches(text)

            async def measure(operation):
                nonlocal queries
                queries = 0
                durations = []
                for _ in range(messages):
                    start = time.perf_counter()
                    await operation()
                    durations.append((time.perf_counter() - start) * 1000)
                return {
                    "database_queries": queries,
                    "median_ms": round(statistics.median(durations), 4),
                    "p95_ms": round(sorted(durations)[int(messages * 0.95)], 4),
                    "total_ms": round(sum(durations), 2),
                }

            previous = await measure(previous_path)
            for kind in ("blacklist", "filters", "settings"):
                await invalidate_rules(kind, chat_id)
            # Include startup compilation separately from steady-state measurements.
            queries = 0
            start = time.perf_counter()
            await asyncio.gather(*(cached_path() for _ in range(50)))
            cold_burst = {
                "concurrent_messages": 50,
                "database_queries": queries,
                "total_ms": round((time.perf_counter() - start) * 1000, 2),
            }
            cached = await measure(cached_path)
            return {
                "messages": messages,
                "blacklist_rules": 200,
                "reply_rules": 200,
                "previous": previous,
                "cached": cached,
                "cold_burst": cold_burst,
                "median_speedup": round(previous["median_ms"] / cached["median_ms"], 1),
            }
        finally:
            for kind in ("blacklist", "filters", "settings"):
                await invalidate_rules(kind, chat_id)
            await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(benchmark()), indent=2))
