import asyncio
import hmac
import json
import math
import tempfile
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from loguru import logger

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


class AsyncSnapshotCache:
    """
    A high-performance, async-native memory cache with LRU eviction and snapshots.
    Uses collections.OrderedDict for O(1) LRU eviction and memory bounds.
    """

    def __init__(
        self,
        snapshot_path: str | Path = "data/cache.snapshot",
        max_size: int = 10000,
        *,
        snapshot_key: bytes | None = None,
    ):
        if max_size < 1:
            raise ValueError("max_size must be positive")
        self.snapshot_path = Path(snapshot_path)
        self._snapshot_key = snapshot_key
        self.max_size = max_size
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._expiries: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._loads: dict[str, asyncio.Task] = {}
        self._volatile_keys: set[str] = set()

        self._hits = 0
        self._misses = 0
        self._evictions = 0

    async def get(self, key: str) -> Any | None:
        """Retrieves an item, updating its LRU position."""
        async with self._lock:
            if key not in self._data:
                self._misses += 1
                return None

            expiry = self._expiries.get(key)
            if expiry is not None and time.time() >= expiry:
                self._delete_internal(key)
                self._misses += 1
                return None

            self._data.move_to_end(key)
            self._hits += 1
            return self._data[key]

    async def set(self, key: str, value: Any, ttl: int | None = None) -> bool:
        """Sets an item with LRU eviction and optional TTL."""
        async with self._lock:
            if key in self._data:
                self._data.move_to_end(key)

            self._loads.pop(key, None)
            self._volatile_keys.discard(key)
            self._data[key] = value
            if ttl is not None:
                self._expiries[key] = time.time() + ttl
            else:
                self._expiries.pop(key, None)

            while len(self._data) > self.max_size:
                self._evict_oldest()

            return True

    async def get_or_load(
        self, key: str, loader: Callable[[], Awaitable[Any]], *, ttl: int = 60
    ) -> Any:
        """Share concurrent misses; loaded values are memory-only and invalidation-safe."""
        value = await self.get(key)
        if value is not None:
            return value
        async with self._lock:
            # Another caller may have filled the key between get() and this lock.
            expiry = self._expiries.get(key)
            if key in self._data and (expiry is None or time.time() < expiry):
                self._data.move_to_end(key)
                return self._data[key]
            task = self._loads.get(key)
            if task is None:
                task = asyncio.create_task(self._load_value(key, loader, ttl))
                self._loads[key] = task
                # Retrieve errors even if every waiting handler is cancelled.
                task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(task)

    async def _load_value(self, key: str, loader: Callable[[], Awaitable[Any]], ttl: int) -> Any:
        task = asyncio.current_task()
        try:
            value = await loader()
            async with self._lock:
                # delete/set during the load supersedes this result.
                if self._loads.get(key) is task:
                    self._data[key] = value
                    self._data.move_to_end(key)
                    self._expiries[key] = time.time() + ttl
                    self._volatile_keys.add(key)
                    while len(self._data) > self.max_size:
                        self._evict_oldest()
            return value
        finally:
            async with self._lock:
                if self._loads.get(key) is task:
                    self._loads.pop(key, None)

    async def setex(self, key: str, ttl: int, value: Any) -> bool:
        """Compatibility wrapper for standard cache setex."""
        return await self.set(key, value, ttl=ttl)

    async def incr(self, key: str) -> int:
        """Increments an integer key with LRU update."""
        async with self._lock:
            expiry = self._expiries.get(key)
            if expiry is not None and time.time() >= expiry:
                self._delete_internal(key)

            current = self._data.get(key, 0)
            if not isinstance(current, int):
                try:
                    current = int(current)
                except (ValueError, TypeError):
                    current = 0

            new_val = current + 1
            self._data[key] = new_val
            self._data.move_to_end(key)

            if len(self._data) > self.max_size:
                self._evict_oldest()

            return new_val

    async def expire(self, key: str, seconds: int) -> bool:
        """Sets/Updates TTL and marks key as recently used."""
        async with self._lock:
            if key not in self._data:
                return False
            expiry = self._expiries.get(key)
            if expiry is not None and time.time() >= expiry:
                self._delete_internal(key)
                return False
            self._expiries[key] = time.time() + seconds
            self._data.move_to_end(key)
            return True

    async def exists(self, key: str) -> bool:
        """Checks existence and updates LRU position."""
        async with self._lock:
            if key not in self._data:
                return False

            expiry = self._expiries.get(key)
            if expiry is not None and time.time() >= expiry:
                self._delete_internal(key)
                return False

            self._data.move_to_end(key)
            return True

    async def get_ttl(self, key: str) -> int:
        """Returns remaining TTL in seconds, or -1 if no TTL, -2 if not exists."""
        async with self._lock:
            if key not in self._data:
                return -2
            expiry = self._expiries.get(key)
            if expiry is None:
                return -1
            now = time.time()
            if now >= expiry:
                self._delete_internal(key)
                return -2
            remaining = int(expiry - now)
            return max(0, remaining)

    async def delete(self, key: str) -> bool:
        """Removes a key from cache."""
        async with self._lock:
            return self._delete_internal(key)

    async def delete_if_value(self, key: str, expected: Any) -> bool:
        """Remove a key only if it still holds the value the caller read."""
        async with self._lock:
            if key not in self._data or self._data[key] != expected:
                return False
            return self._delete_internal(key)

    def _delete_internal(self, key: str) -> bool:
        """Internal helper to delete a key without acquiring the lock."""
        self._loads.pop(key, None)
        self._volatile_keys.discard(key)
        self._expiries.pop(key, None)
        if key not in self._data:
            return False
        del self._data[key]
        return True

    def _evict_oldest(self) -> None:
        """Removes the least recently used item."""
        if not self._data:
            return
        key, _ = self._data.popitem(last=False)
        self._expiries.pop(key, None)
        self._volatile_keys.discard(key)
        self._evictions += 1
        logger.debug(f"Cache reached {self.max_size} items. Evicted oldest (LRU): {key}")

    async def stats(self) -> dict[str, Any]:
        """Returns cache usage statistics."""
        async with self._lock:
            return {
                "size": len(self._data),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": f"{(self._hits / (self._hits + self._misses) * 100):.2f}%"
                if (self._hits + self._misses) > 0
                else "0%",
            }

    async def cleanup_expired(self) -> int:
        """Purges all expired keys."""
        async with self._lock:
            now = time.time()
            expired_keys = [k for k, exp in self._expiries.items() if now >= exp]
            for k in expired_keys:
                self._delete_internal(k)
            return len(expired_keys)

    async def save_snapshot(self) -> bool:
        """Capture under the memory lock; serialize snapshots without blocking cache traffic."""
        async with self._snapshot_lock:
            try:
                async with self._lock:
                    data = {k: v for k, v in self._data.items() if k not in self._volatile_keys}
                    state = {
                        "data": data,
                        "expiries": {k: v for k, v in self._expiries.items() if k in data},
                    }

                def _save_io():
                    payload = json.dumps(state, allow_nan=False).encode()
                    if self._snapshot_key is not None:
                        signature = hmac.digest(self._snapshot_key, payload, "sha256")
                        payload = signature + payload
                    if len(payload) > MAX_SNAPSHOT_BYTES:
                        raise ValueError("Cache snapshot is too large")
                    self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(
                        dir=self.snapshot_path.parent, delete=False
                    ) as f:
                        temp_path = Path(f.name)
                        try:
                            f.write(payload)
                            f.close()
                            temp_path.replace(self.snapshot_path)
                        finally:
                            temp_path.unlink(missing_ok=True)

                await asyncio.to_thread(_save_io)
                logger.debug(f"Cache snapshot saved: {len(data)} items.")
                return True
            except Exception as e:
                logger.error(f"Failed to save cache snapshot: {e}")
                return False

    async def load_snapshot(self) -> bool:
        """Loads cache state and restores LRU order."""
        if not self.snapshot_path.exists():
            return False

        async with self._snapshot_lock, self._lock:
            try:

                def _load_io():
                    with open(self.snapshot_path, "rb") as f:
                        payload = f.read(MAX_SNAPSHOT_BYTES + 1)
                    if len(payload) > MAX_SNAPSHOT_BYTES:
                        raise ValueError("Cache snapshot is too large")
                    if self._snapshot_key is not None:
                        signature, payload = payload[:32], payload[32:]
                        expected = hmac.digest(self._snapshot_key, payload, "sha256")
                        if not hmac.compare_digest(signature, expected):
                            raise ValueError("Invalid cache snapshot signature")
                    state = json.loads(payload)
                    if not isinstance(state, dict):
                        raise ValueError("Invalid cache snapshot")
                    data, expiries = state.get("data"), state.get("expiries")
                    if not isinstance(data, dict) or not isinstance(expiries, dict):
                        raise ValueError("Invalid cache snapshot entries")
                    if any(
                        key not in data
                        or type(expiry) not in (int, float)
                        or not math.isfinite(expiry)
                        for key, expiry in expiries.items()
                    ):
                        raise ValueError("Invalid cache snapshot expiry")
                    return data, expiries

                data, expiries = await asyncio.to_thread(_load_io)

                self._loads.clear()
                self._volatile_keys.clear()
                self._data = OrderedDict(data)
                self._expiries = expiries

                now = time.time()
                expired_keys = [k for k, exp in self._expiries.items() if now >= exp]
                for k in expired_keys:
                    self._data.pop(k, None)
                    self._expiries.pop(k, None)

                while len(self._data) > self.max_size:
                    self._evict_oldest()

                logger.debug(f"Loaded cache snapshot: {len(self._data)} items.")
                return True
            except Exception as e:
                logger.error(f"Failed to load cache snapshot: {e}")
                return False


_cache: AsyncSnapshotCache | None = None


def get_cache() -> AsyncSnapshotCache:
    """Returns the global AsyncSnapshotCache instance."""
    global _cache
    if _cache is None:
        from src.config import config

        snapshot_key = hmac.digest(config.BOT_TOKEN.encode(), b"lex-tg cache snapshot v1", "sha256")
        _cache = AsyncSnapshotCache(snapshot_key=snapshot_key)
    return _cache
