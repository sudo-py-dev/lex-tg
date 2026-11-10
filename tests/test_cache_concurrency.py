import asyncio
import threading
from unittest.mock import AsyncMock

import pytest

from src.utils.local_cache import AsyncSnapshotCache


async def test_simultaneous_misses_share_one_load_and_cache_empty_results():
    cache = AsyncSnapshotCache()
    started, release = asyncio.Event(), asyncio.Event()

    async def load():
        started.set()
        await release.wait()
        return ()

    loader = AsyncMock(side_effect=load)
    tasks = [asyncio.create_task(cache.get_or_load("key", loader)) for _ in range(50)]
    await started.wait()
    release.set()
    assert await asyncio.gather(*tasks) == [()] * 50
    assert await cache.get_or_load("key", loader) == ()
    loader.assert_awaited_once()


@pytest.mark.parametrize("overwrite", [False, True])
async def test_invalidation_during_load_cannot_restore_stale_data(overwrite):
    cache = AsyncSnapshotCache()
    started, release = asyncio.Event(), asyncio.Event()

    async def old():
        started.set()
        await release.wait()
        return "old"

    task = asyncio.create_task(cache.get_or_load("rules", old))
    await started.wait()
    if overwrite:
        await cache.set("rules", "new")
    else:
        await cache.delete("rules")
        assert await cache.get_or_load("rules", AsyncMock(return_value="new")) == "new"
    release.set()
    assert await task == "old"
    assert await cache.get("rules") == "new"


async def test_cancelled_waiter_does_not_cancel_shared_load():
    cache = AsyncSnapshotCache()
    started, release = asyncio.Event(), asyncio.Event()

    async def load():
        started.set()
        await release.wait()
        return 42

    first = asyncio.create_task(cache.get_or_load("key", load))
    await started.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    second = asyncio.create_task(cache.get_or_load("key", load))
    release.set()
    assert await second == 42


async def test_failed_load_is_not_cached_and_can_retry():
    cache = AsyncSnapshotCache()
    with pytest.raises(RuntimeError):
        await cache.get_or_load("key", AsyncMock(side_effect=RuntimeError("DB unavailable")))
    assert await cache.get_or_load("key", AsyncMock(return_value=0)) == 0


async def test_loader_ttl_capacity_and_snapshot_exclusion(tmp_path, mocker):
    cache = AsyncSnapshotCache(str(tmp_path / "cache.pkl"), max_size=2)
    now = mocker.patch("src.utils.local_cache.time.time", return_value=100)
    await cache.set("persistent", "keep")
    await cache.get_or_load("rules", AsyncMock(return_value="old"), ttl=1)
    assert await cache.save_snapshot()
    restored = AsyncSnapshotCache(str(tmp_path / "cache.pkl"))
    assert await restored.load_snapshot()
    assert await restored.get("persistent") == "keep"
    assert await restored.get("rules") is None
    now.return_value = 101
    assert await cache.get_or_load("rules", AsyncMock(return_value="fresh")) == "fresh"
    await cache.get_or_load("other", AsyncMock(return_value="value"))
    assert (await cache.stats())["size"] == 2
    assert await cache.get("persistent") is None


async def test_slow_snapshot_does_not_block_cache_operations(tmp_path, mocker):
    cache = AsyncSnapshotCache(str(tmp_path / "cache.pkl"))
    await cache.set("live", 1)
    started, release = threading.Event(), threading.Event()
    import pickle

    original = pickle.dump

    def slow_dump(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    mocker.patch("src.utils.local_cache.pickle.dump", side_effect=slow_dump)
    saving = asyncio.create_task(cache.save_snapshot())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert await asyncio.wait_for(cache.get("live"), timeout=1) == 1
        assert await asyncio.wait_for(cache.set("live", 2), timeout=1)
    finally:
        release.set()
        assert await saving
    assert await cache.get("live") == 2
