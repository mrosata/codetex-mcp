from __future__ import annotations

import asyncio
import time

import pytest

from codetex_mcp.llm.rate_limiter import RateLimiter


class TestAcquireRelease:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        limiter = RateLimiter(max_concurrent=2)
        await limiter.acquire()
        await limiter.acquire()
        await limiter.release()
        await limiter.release()

    @pytest.mark.asyncio
    async def test_acquire_blocks_at_capacity(self) -> None:
        limiter = RateLimiter(max_concurrent=1)
        await limiter.acquire()

        acquired = False

        async def try_acquire() -> None:
            nonlocal acquired
            await limiter.acquire()
            acquired = True

        task = asyncio.create_task(try_acquire())
        await asyncio.sleep(0.05)
        assert not acquired

        await limiter.release()
        await task
        assert acquired


class TestConcurrencyLimiting:
    @pytest.mark.asyncio
    async def test_limits_concurrency(self) -> None:
        max_concurrent = 2
        limiter = RateLimiter(max_concurrent=max_concurrent)
        active = 0
        max_active = 0

        async def worker() -> None:
            nonlocal active, max_active
            await limiter.acquire()
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            await limiter.release()

        tasks = [worker() for _ in range(5)]
        await asyncio.gather(*tasks)

        assert max_active <= max_concurrent

    @pytest.mark.asyncio
    async def test_all_workers_complete(self) -> None:
        limiter = RateLimiter(max_concurrent=2)
        completed = 0

        async def worker() -> None:
            nonlocal completed
            await limiter.acquire()
            await asyncio.sleep(0.01)
            completed += 1
            await limiter.release()

        tasks = [worker() for _ in range(4)]
        await asyncio.gather(*tasks)

        assert completed == 4


class TestHandleRateLimit:
    @pytest.mark.asyncio
    async def test_handle_rate_limit_waits(self) -> None:
        limiter = RateLimiter(max_concurrent=1, base_delay=0.05, max_delay=1.0)
        start = time.monotonic()
        await limiter.handle_rate_limit()
        elapsed = time.monotonic() - start
        # Should wait some amount (jitter between 0 and base_delay)
        assert elapsed >= 0

    @pytest.mark.asyncio
    async def test_consecutive_rate_limits_increase_delay(self) -> None:
        limiter = RateLimiter(max_concurrent=1, base_delay=0.01, max_delay=10.0)
        # First rate limit: delay up to 0.01
        await limiter.handle_rate_limit()
        # Second rate limit: delay up to 0.02
        await limiter.handle_rate_limit()
        # Third rate limit: delay up to 0.04
        await limiter.handle_rate_limit()
        assert limiter._consecutive_rate_limits == 3

    @pytest.mark.asyncio
    async def test_release_resets_consecutive_count(self) -> None:
        limiter = RateLimiter(max_concurrent=1)
        await limiter.acquire()
        await limiter.handle_rate_limit()
        await limiter.handle_rate_limit()
        assert limiter._consecutive_rate_limits == 2
        await limiter.release()
        assert limiter._consecutive_rate_limits == 0

    @pytest.mark.asyncio
    async def test_delay_capped_at_max(self) -> None:
        limiter = RateLimiter(max_concurrent=1, base_delay=1.0, max_delay=0.05)
        start = time.monotonic()
        await limiter.handle_rate_limit()
        elapsed = time.monotonic() - start
        # Jitter is between 0 and max_delay, so elapsed should be at most max_delay + overhead
        assert elapsed < 0.2
