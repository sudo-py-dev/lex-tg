import asyncio
from pathlib import Path

import pytest

from src.utils.local_cache import AsyncSnapshotCache


@pytest.fixture
def cache_dir(tmp_path):
    """Fixture to provide a temporary directory for cache snapshots."""
    return tmp_path / "cache"


@pytest.fixture
async def cache(cache_dir):
    """Fixture to provide a clean AsyncSnapshotCache instance."""
    snapshot_path = cache_dir / "test_snapshot.pkl"
    c = AsyncSnapshotCache(snapshot_path=str(snapshot_path), max_size=5)
    return c


@pytest.mark.asyncio
async def test_basic_ops(cache):

    assert await cache.set("key1", "val1") is True
    assert await cache.get("key1") == "val1"

    assert await cache.exists("key1") is True
    assert await cache.exists("key2") is False

    assert await cache.delete("key1") is True
    assert await cache.get("key1") is None
    assert await cache.delete("key2") is False


@pytest.mark.asyncio
async def test_ttl_expiry(cache):

    await cache.set("key_ttl", "val", ttl=1)
    assert await cache.get("key_ttl") == "val"

    await asyncio.sleep(1.1)
    assert await cache.get("key_ttl") is None


@pytest.mark.asyncio
async def test_incr(cache):

    assert await cache.incr("counter") == 1
    assert await cache.incr("counter") == 2

    await cache.set("c2", 10, ttl=1)
    assert await cache.incr("c2") == 11
    await asyncio.sleep(1.1)
    assert await cache.incr("c2") == 1


@pytest.mark.asyncio
async def test_lru_eviction(cache):

    for i in range(5):
        await cache.set(f"key{i}", i)

    assert (await cache.stats())["size"] == 5

    await cache.get("key0")

    await cache.set("key5", 5)

    assert await cache.get("key0") == 0
    assert await cache.get("key5") == 5
    assert await cache.get("key1") is None
    assert (await cache.stats())["evictions"] == 1


@pytest.mark.asyncio
async def test_persistence(cache):
    await cache.set("p1", "persist_this")
    await cache.set("p2", {"complex": "data"})

    assert await cache.save_snapshot() is True
    assert Path(cache.snapshot_path).exists()

    new_cache = AsyncSnapshotCache(snapshot_path=cache.snapshot_path)
    assert await new_cache.load_snapshot() is True

    assert await new_cache.get("p1") == "persist_this"
    assert await new_cache.get("p2") == {"complex": "data"}


async def test_signed_snapshot_rejects_modified_payload(tmp_path):
    snapshot = tmp_path / "cache.snapshot"
    cache = AsyncSnapshotCache(snapshot, snapshot_key=b"test-signing-key")
    await cache.set("state", "original")
    assert await cache.save_snapshot()

    restored = AsyncSnapshotCache(snapshot, snapshot_key=b"test-signing-key")
    assert await restored.load_snapshot()
    assert await restored.get("state") == "original"
    snapshot.write_bytes(snapshot.read_bytes().replace(b"original", b"modified"))
    assert not await restored.load_snapshot()
    assert await restored.get("state") == "original"


@pytest.mark.asyncio
async def test_stats(cache):
    await cache.set("k1", 1)
    await cache.get("k1")
    await cache.get("k2")

    stats = await cache.stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["size"] == 1
