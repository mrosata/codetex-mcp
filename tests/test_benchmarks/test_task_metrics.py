"""Unit tests for task completion metric calculations."""

from __future__ import annotations

import pytest

from codetex_mcp.benchmarks.task_metrics import (
    aggregate_correctness,
    exact_match,
    keyword_overlap,
    line_coverage,
    success_rate,
    symbol_presence,
)


class TestExactMatch:
    def test_identical(self) -> None:
        assert exact_match("hello", "hello") == 1.0

    def test_different(self) -> None:
        assert exact_match("hello", "world") == 0.0

    def test_whitespace_stripped(self) -> None:
        assert exact_match("  hello  ", "hello") == 1.0

    def test_case_sensitive(self) -> None:
        assert exact_match("Hello", "hello") == 0.0

    def test_empty_expected(self) -> None:
        assert exact_match("", "hello") == 0.0

    def test_empty_actual(self) -> None:
        assert exact_match("hello", "") == 0.0

    def test_both_empty(self) -> None:
        assert exact_match("", "") == 0.0


class TestLineCoverage:
    def test_all_present(self) -> None:
        expected = ["def foo():", "return 42"]
        actual = "def foo():\n    return 42"
        assert line_coverage(expected, actual) == 1.0

    def test_none_present(self) -> None:
        expected = ["def foo():", "return 42"]
        actual = "class Bar:\n    pass"
        assert line_coverage(expected, actual) == 0.0

    def test_partial_present(self) -> None:
        expected = ["def foo():", "return 42", "print(x)"]
        actual = "def foo():\n    return 42"
        assert line_coverage(expected, actual) == pytest.approx(2 / 3)

    def test_empty_expected(self) -> None:
        assert line_coverage([], "some code") == 0.0

    def test_empty_actual(self) -> None:
        expected = ["def foo():"]
        assert line_coverage(expected, "") == 0.0

    def test_stripped_matching(self) -> None:
        expected = ["  def foo():  "]
        actual = "def foo():"
        assert line_coverage(expected, actual) == 1.0


class TestSymbolPresence:
    def test_all_found(self) -> None:
        symbols = ["SearchEngine", "search", "embed"]
        actual = "class SearchEngine:\n    def search(self):\n        embed(query)"
        assert symbol_presence(symbols, actual) == 1.0

    def test_none_found(self) -> None:
        symbols = ["SearchEngine", "embed"]
        actual = "class Foo:\n    pass"
        assert symbol_presence(symbols, actual) == 0.0

    def test_partial_found(self) -> None:
        symbols = ["SearchEngine", "embed", "query"]
        actual = "class SearchEngine:\n    pass"
        assert symbol_presence(symbols, actual) == pytest.approx(1 / 3)

    def test_case_sensitive(self) -> None:
        symbols = ["SearchEngine"]
        actual = "searchengine"
        assert symbol_presence(symbols, actual) == 0.0

    def test_empty_symbols(self) -> None:
        assert symbol_presence([], "some code") == 0.0

    def test_empty_actual(self) -> None:
        assert symbol_presence(["foo"], "") == 0.0


class TestKeywordOverlap:
    def test_all_found(self) -> None:
        keywords = ["search", "query", "embed"]
        actual = "Search for a query and embed the results"
        assert keyword_overlap(keywords, actual) == 1.0

    def test_none_found(self) -> None:
        keywords = ["search", "query"]
        actual = "This is unrelated content"
        assert keyword_overlap(keywords, actual) == 0.0

    def test_partial_found(self) -> None:
        keywords = ["search", "query", "index"]
        actual = "search for results"
        assert keyword_overlap(keywords, actual) == pytest.approx(1 / 3)

    def test_case_insensitive(self) -> None:
        keywords = ["Search", "QUERY"]
        actual = "search and query"
        assert keyword_overlap(keywords, actual) == 1.0

    def test_empty_keywords(self) -> None:
        assert keyword_overlap([], "some code") == 0.0

    def test_empty_actual(self) -> None:
        assert keyword_overlap(["foo"], "") == 0.0


class TestAggregateCorrectness:
    def test_all_perfect(self) -> None:
        assert aggregate_correctness(1.0, 1.0, 1.0) == pytest.approx(1.0)

    def test_all_zero(self) -> None:
        assert aggregate_correctness(0.0, 0.0, 0.0) == 0.0

    def test_weights_applied(self) -> None:
        # symbol=0.4, keyword=0.3, line=0.3
        result = aggregate_correctness(1.0, 0.0, 0.0)
        assert result == pytest.approx(0.4)

    def test_keyword_weight(self) -> None:
        result = aggregate_correctness(0.0, 1.0, 0.0)
        assert result == pytest.approx(0.3)

    def test_line_weight(self) -> None:
        result = aggregate_correctness(0.0, 0.0, 1.0)
        assert result == pytest.approx(0.3)

    def test_mixed_scores(self) -> None:
        result = aggregate_correctness(0.5, 0.8, 0.6)
        expected = 0.4 * 0.5 + 0.3 * 0.8 + 0.3 * 0.6
        assert result == pytest.approx(expected)


class TestSuccessRate:
    def test_all_passing(self) -> None:
        assert success_rate([0.8, 0.9, 1.0]) == 1.0

    def test_none_passing(self) -> None:
        assert success_rate([0.1, 0.2, 0.3]) == 0.0

    def test_partial_passing(self) -> None:
        assert success_rate([0.3, 0.5, 0.8]) == pytest.approx(2 / 3)

    def test_custom_threshold(self) -> None:
        assert success_rate([0.3, 0.5, 0.8], threshold=0.7) == pytest.approx(1 / 3)

    def test_empty_scores(self) -> None:
        assert success_rate([]) == 0.0

    def test_at_threshold(self) -> None:
        # Score exactly at threshold counts as passing
        assert success_rate([0.5], threshold=0.5) == 1.0

    def test_just_below_threshold(self) -> None:
        assert success_rate([0.499], threshold=0.5) == 0.0
