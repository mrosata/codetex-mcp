from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from codetex_mcp.exceptions import LLMError, RateLimitError
from codetex_mcp.llm.provider import AnthropicProvider, LLMProvider
from codetex_mcp.llm.rate_limiter import RateLimiter


class TestLLMProviderABC:
    def test_cannot_instantiate_abstract(self) -> None:
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore[abstract]

    def test_subclass_must_implement_summarize(self) -> None:
        class Incomplete(LLMProvider):
            async def summarize_batch(
                self, prompts: list[str], system: str | None = None
            ) -> list[str]:
                return []

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_subclass_must_implement_summarize_batch(self) -> None:
        class Incomplete(LLMProvider):
            async def summarize(self, prompt: str, system: str | None = None) -> str:
                return ""

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


class TestAnthropicProviderInit:
    def test_creates_with_api_key(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        assert provider._model == "claude-sonnet-4-5-20250929"

    def test_custom_model(self) -> None:
        provider = AnthropicProvider(
            api_key="test-key", model="claude-haiku-4-5-20251001"
        )
        assert provider._model == "claude-haiku-4-5-20251001"

    def test_custom_rate_limiter(self) -> None:
        limiter = RateLimiter(max_concurrent=3)
        provider = AnthropicProvider(api_key="test-key", rate_limiter=limiter)
        assert provider._rate_limiter is limiter

    def test_default_rate_limiter_created(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        assert isinstance(provider._rate_limiter, RateLimiter)


class TestAnthropicProviderSummarize:
    @pytest.mark.asyncio
    async def test_returns_text_from_response(self) -> None:
        provider = AnthropicProvider(api_key="test-key")

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "This is a summary."

        mock_response = MagicMock()
        mock_response.content = [mock_block]

        provider._client.messages.create = AsyncMock(return_value=mock_response)

        result = await provider.summarize("Summarize this code")
        assert result == "This is a summary."

    @pytest.mark.asyncio
    async def test_passes_system_prompt(self) -> None:
        provider = AnthropicProvider(api_key="test-key")

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "response"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        provider._client.messages.create = AsyncMock(return_value=mock_response)

        await provider.summarize("prompt", system="You are a code analyzer.")
        call_kwargs = provider._client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "You are a code analyzer."

    @pytest.mark.asyncio
    async def test_no_system_prompt_omitted(self) -> None:
        provider = AnthropicProvider(api_key="test-key")

        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "response"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        provider._client.messages.create = AsyncMock(return_value=mock_response)

        await provider.summarize("prompt")
        call_kwargs = provider._client.messages.create.call_args
        assert "system" not in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_multiple_text_blocks_joined(self) -> None:
        provider = AnthropicProvider(api_key="test-key")

        block1 = MagicMock()
        block1.type = "text"
        block1.text = "Part one."
        block2 = MagicMock()
        block2.type = "text"
        block2.text = "Part two."

        mock_response = MagicMock()
        mock_response.content = [block1, block2]

        provider._client.messages.create = AsyncMock(return_value=mock_response)

        result = await provider.summarize("prompt")
        assert result == "Part one.\nPart two."

    @pytest.mark.asyncio
    async def test_rate_limit_error_raised(self) -> None:
        import anthropic

        provider = AnthropicProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.text = "Rate limited"

        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=mock_response,
                body=None,
            )
        )

        with pytest.raises(RateLimitError):
            await provider.summarize("prompt")

    @pytest.mark.asyncio
    async def test_api_error_raised_as_llm_error(self) -> None:
        import anthropic

        provider = AnthropicProvider(api_key="test-key")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}
        mock_response.text = "Internal error"

        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.APIError(
                message="server error",
                request=MagicMock(),
                body=None,
            )
        )

        with pytest.raises(LLMError):
            await provider.summarize("prompt")


class TestAnthropicProviderSummarizeBatch:
    @pytest.mark.asyncio
    async def test_returns_results_for_all_prompts(self) -> None:
        provider = AnthropicProvider(api_key="test-key")

        call_count = 0

        async def mock_create(**kwargs: object) -> MagicMock:
            nonlocal call_count
            call_count += 1
            block = MagicMock()
            block.type = "text"
            block.text = f"Response {call_count}"
            response = MagicMock()
            response.content = [block]
            return response

        provider._client.messages.create = AsyncMock(side_effect=mock_create)

        results = await provider.summarize_batch(["p1", "p2", "p3"])
        assert len(results) == 3
        assert all(r.startswith("Response") for r in results)

    @pytest.mark.asyncio
    async def test_empty_prompts_returns_empty(self) -> None:
        provider = AnthropicProvider(api_key="test-key")
        results = await provider.summarize_batch([])
        assert results == []

    @pytest.mark.asyncio
    async def test_retries_on_rate_limit(self) -> None:
        import anthropic

        limiter = RateLimiter(max_concurrent=5, base_delay=0.01, max_delay=0.02)
        provider = AnthropicProvider(api_key="test-key", rate_limiter=limiter)

        attempts = 0

        async def mock_create(**kwargs: object) -> MagicMock:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                mock_resp = MagicMock()
                mock_resp.status_code = 429
                mock_resp.headers = {}
                mock_resp.text = "Rate limited"
                raise anthropic.RateLimitError(
                    message="rate limited",
                    response=mock_resp,
                    body=None,
                )
            block = MagicMock()
            block.type = "text"
            block.text = "Success"
            response = MagicMock()
            response.content = [block]
            return response

        provider._client.messages.create = AsyncMock(side_effect=mock_create)

        results = await provider.summarize_batch(["prompt"])
        assert results == ["Success"]
        assert attempts == 2

    @pytest.mark.asyncio
    async def test_respects_concurrency_limit(self) -> None:
        max_concurrent = 2
        limiter = RateLimiter(max_concurrent=max_concurrent)
        provider = AnthropicProvider(api_key="test-key", rate_limiter=limiter)

        active = 0
        max_active = 0

        async def mock_create(**kwargs: object) -> MagicMock:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            block = MagicMock()
            block.type = "text"
            block.text = "ok"
            response = MagicMock()
            response.content = [block]
            return response

        provider._client.messages.create = AsyncMock(side_effect=mock_create)

        await provider.summarize_batch(["p1", "p2", "p3", "p4", "p5"])
        assert max_active <= max_concurrent
