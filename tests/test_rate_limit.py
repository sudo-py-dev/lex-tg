import asyncio
import unittest

from src.utils.rate_limit import TokenBucketLimiter


class RateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_impossible_cost_is_rejected(self):
        limiter = TokenBucketLimiter(rate=10, burst=2)
        for cost in (3, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                await asyncio.wait_for(limiter.wait(cost=cost), timeout=0.1)
        self.assertEqual(limiter._states, {})

    async def test_full_burst_and_independent_keys(self):
        limiter = TokenBucketLimiter(rate=1, burst=2)
        await asyncio.wait_for(limiter.wait("a", cost=2), timeout=0.1)
        await asyncio.wait_for(limiter.wait("b", cost=2), timeout=0.1)
