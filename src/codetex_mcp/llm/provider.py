"""LLM provider abstraction with Anthropic implementation."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

import anthropic
from anthropic.types import MessageParam

from codetex_mcp.exceptions import LLMError, RateLimitError
from codetex_mcp.llm.rate_limiter import RateLimiter


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def summarize(self, prompt: str, system: str | None = None) -> str:
        """Send a single prompt to the LLM and return the response text."""
        ...

    @abstractmethod
    async def summarize_batch(
        self, prompts: list[str], system: str | None = None
    ) -> list[str]:
        """Send multiple prompts concurrently with rate limiting."""
        ...


class AnthropicProvider(LLMProvider):
    """Anthropic Claude implementation of LLMProvider."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._rate_limiter = rate_limiter or RateLimiter()

    async def summarize(self, prompt: str, system: str | None = None) -> str:
        """Send a single prompt to Claude and return the response text."""
        messages: list[MessageParam] = [{"role": "user", "content": prompt}]

        try:
            if system:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    messages=messages,
                    system=system,
                )
            else:
                response = await self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    messages=messages,
                )
        except anthropic.RateLimitError as e:
            raise RateLimitError(str(e)) from e
        except anthropic.APIError as e:
            raise LLMError(str(e)) from e

        # Extract text from the response content blocks
        text_parts = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        return "\n".join(text_parts)

    async def summarize_batch(
        self, prompts: list[str], system: str | None = None
    ) -> list[str]:
        """Send multiple prompts concurrently with rate limiting and retry on rate limit."""
        results: list[str | None] = [None] * len(prompts)

        async def _call(index: int, prompt: str) -> None:
            await self._rate_limiter.acquire()
            try:
                while True:
                    try:
                        result = await self.summarize(prompt, system)
                        results[index] = result
                        return
                    except RateLimitError:
                        await self._rate_limiter.handle_rate_limit()
            finally:
                await self._rate_limiter.release()

        tasks = [_call(i, p) for i, p in enumerate(prompts)]
        await asyncio.gather(*tasks)

        return [r if r is not None else "" for r in results]
