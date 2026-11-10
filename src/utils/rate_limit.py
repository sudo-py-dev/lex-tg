from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass


@dataclass
class _BucketState:
    tokens: float
    last_ts: float
    blocked_until: float = 0.0


class TokenBucketLimiter:
    """
    Async token-bucket limiter with optional per-key states.

    - rate: tokens refilled per second
    - burst: max tokens stored
    """

    def __init__(self, rate: float, burst: float) -> None:
        self.rate = max(0.01, float(rate))
        self.burst = max(1.0, float(burst))
        self._states: dict[str, _BucketState] = {}
        self._lock = asyncio.Lock()

    async def wait(self, key: str = "global", cost: float = 1.0) -> None:
        """Wait until enough tokens are available for this key."""
        requested = float(cost)
        if not math.isfinite(requested) or requested > self.burst:
            raise ValueError("cost must be finite and cannot exceed burst capacity")
        need = max(0.01, requested)
        while True:
            sleep_for = 0.0
            async with self._lock:
                now = time.monotonic()
                st = self._states.get(key)
                if st is None:
                    st = _BucketState(tokens=self.burst, last_ts=now)
                    self._states[key] = st

                elapsed = max(0.0, now - st.last_ts)
                st.tokens = min(self.burst, st.tokens + (elapsed * self.rate))
                st.last_ts = now

                if st.blocked_until > now:
                    sleep_for = st.blocked_until - now
                elif st.tokens >= need:
                    st.tokens -= need
                    return
                else:
                    deficit = need - st.tokens
                    sleep_for = max(deficit / self.rate, 0.01)

            await asyncio.sleep(min(sleep_for, 5.0))

    async def penalize(self, key: str, seconds: float) -> None:
        """Temporarily block key and drain tokens after FloodWait-like events."""
        penalty = max(0.0, float(seconds))
        async with self._lock:
            now = time.monotonic()
            st = self._states.get(key)
            if st is None:
                st = _BucketState(tokens=0.0, last_ts=now)
                self._states[key] = st
            st.tokens = 0.0
            st.blocked_until = max(st.blocked_until, now + penalty)
