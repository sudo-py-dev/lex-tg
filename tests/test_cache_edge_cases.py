"""Regression tests for cache expiry boundaries and snapshot capacity."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.utils.local_cache import AsyncSnapshotCache


class CacheEdgeCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_expiry_boundary_across_operations(self):
        cache = AsyncSnapshotCache()
        with patch("src.utils.local_cache.time.time", return_value=100):
            for key in ("get", "exists", "incr", "expire", "ttl", "cleanup"):
                await cache.set(key, 10, ttl=1)
        with patch("src.utils.local_cache.time.time", return_value=101):
            self.assertIsNone(await cache.get("get"))
            self.assertFalse(await cache.exists("exists"))
            self.assertEqual(await cache.incr("incr"), 1)
            self.assertFalse(await cache.expire("expire", 100))
            self.assertEqual(await cache.get_ttl("ttl"), -2)
            self.assertEqual(await cache.cleanup_expired(), 1)

    async def test_zero_ttl_expires_immediately(self):
        cache = AsyncSnapshotCache()
        await cache.set("key", "value", ttl=0)
        self.assertFalse(await cache.exists("key"))

    async def test_delete_stored_none(self):
        cache = AsyncSnapshotCache()
        await cache.set("key", None)
        self.assertTrue(await cache.delete("key"))
        self.assertFalse(await cache.delete("key"))

    async def test_restore_preserves_lru_and_enforces_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "cache.pkl")
            cache = AsyncSnapshotCache(path, max_size=3)
            for key in ("a", "b", "c"):
                await cache.set(key, key)
            await cache.get("a")
            self.assertTrue(await cache.save_snapshot())
            restored = AsyncSnapshotCache(path, max_size=2)
            self.assertTrue(await restored.load_snapshot())
            self.assertEqual((await restored.stats())["size"], 2)
            self.assertFalse(await restored.exists("b"))
            self.assertTrue(await restored.exists("a"))
            self.assertTrue(await restored.exists("c"))

    def test_invalid_capacity(self):
        for size in (0, -1):
            with self.assertRaises(ValueError):
                AsyncSnapshotCache(max_size=size)
