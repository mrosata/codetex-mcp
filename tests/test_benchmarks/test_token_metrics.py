"""Unit tests for token efficiency metric calculations."""

from __future__ import annotations

import pytest

from codetex_mcp.benchmarks.token_metrics import (
    compression_ratio,
    count_tokens,
    coverage_score,
    token_density,
)


class TestCountTokens:
    def test_empty_string(self) -> None:
        assert count_tokens("") == 0

    def test_single_word(self) -> None:
        result = count_tokens("hello")
        assert result > 0

    def test_longer_text(self) -> None:
        short = count_tokens("hello")
        long = count_tokens("hello world this is a longer sentence")
        assert long > short

    def test_code_snippet(self) -> None:
        code = "def foo(x: int) -> int:\n    return x + 1"
        result = count_tokens(code)
        assert result > 0

    def test_deterministic(self) -> None:
        text = "The quick brown fox"
        assert count_tokens(text) == count_tokens(text)


class TestCompressionRatio:
    def test_equal_tokens(self) -> None:
        assert compression_ratio(100, 100) == 1.0

    def test_compressed(self) -> None:
        assert compression_ratio(1000, 100) == 10.0

    def test_expanded(self) -> None:
        assert compression_ratio(50, 100) == 0.5

    def test_zero_compressed(self) -> None:
        assert compression_ratio(100, 0) == 0.0

    def test_negative_compressed(self) -> None:
        assert compression_ratio(100, -1) == 0.0

    def test_zero_baseline(self) -> None:
        assert compression_ratio(0, 100) == 0.0


class TestCoverageScore:
    def test_all_found(self) -> None:
        content = "The SearchEngine.search method calls embed and query"
        symbols = ["SearchEngine", "search", "embed"]
        assert coverage_score(content, symbols) == 1.0

    def test_none_found(self) -> None:
        content = "This is unrelated content"
        symbols = ["SearchEngine", "embed"]
        assert coverage_score(content, symbols) == 0.0

    def test_partial_found(self) -> None:
        content = "The SearchEngine handles results"
        symbols = ["SearchEngine", "embed", "query"]
        # "SearchEngine" found, "embed" not found, "query" not found
        assert coverage_score(content, symbols) == pytest.approx(1 / 3)

    def test_case_insensitive(self) -> None:
        content = "searchengine EMBED"
        symbols = ["SearchEngine", "embed"]
        assert coverage_score(content, symbols) == 1.0

    def test_empty_symbols(self) -> None:
        assert coverage_score("some content", []) == 0.0

    def test_empty_content(self) -> None:
        assert coverage_score("", ["symbol"]) == 0.0

    def test_substring_match(self) -> None:
        content = "The _build_directory_tree helper"
        symbols = ["_build_directory_tree"]
        assert coverage_score(content, symbols) == 1.0


class TestTokenDensity:
    def test_all_relevant(self) -> None:
        assert token_density(100, 100) == 1.0

    def test_half_relevant(self) -> None:
        assert token_density(50, 100) == 0.5

    def test_none_relevant(self) -> None:
        assert token_density(0, 100) == 0.0

    def test_zero_total(self) -> None:
        assert token_density(50, 0) == 0.0

    def test_negative_total(self) -> None:
        assert token_density(50, -1) == 0.0
