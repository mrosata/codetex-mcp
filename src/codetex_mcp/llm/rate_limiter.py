"""Rate limiter for LLM API calls with concurrency control and exponential backoff."""

from __future__ import annotations

import asyncio
import random


class RateLimiter:
    """Controls concurrent LLM API calls using a semaphore with exponential backoff on rate limits."""

    def __init__(
        self,
        max_concurrent: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._consecutive_rate_limits = 0

    async def acquire(self) -> None:
        """Acquire a slot for an API call (blocks if at capacity)."""
        await self._semaphore.acquire()

    async def release(self) -> None:
        """Release a slot after an API call completes."""
        self._semaphore.release()
        self._consecutive_rate_limits = 0

    async def handle_rate_limit(self) -> None:
        """Wait with exponential backoff and jitter before retrying after a rate limit."""
        self._consecutive_rate_limits += 1
        delay = min(
            self._base_delay * (2 ** (self._consecutive_rate_limits - 1)),
            self._max_delay,
        )
        # Add jitter: random value between 0 and delay
        jitter = random.uniform(0, delay)  # noqa: S311
        await asyncio.sleep(jitter)
