"""Unit tests for IR metric calculations."""

from __future__ import annotations

import math

import pytest

from codetex_mcp.benchmarks.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


class TestPrecisionAtK:
    def test_all_relevant(self) -> None:
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(retrieved, relevant, 3) == 1.0

    def test_none_relevant(self) -> None:
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(retrieved, relevant, 3) == 0.0

    def test_partial_relevant(self) -> None:
        retrieved = ["a", "x", "b", "y"]
        relevant = {"a", "b", "c"}
        assert precision_at_k(retrieved, relevant, 4) == 0.5

    def test_k_less_than_retrieved(self) -> None:
        retrieved = ["a", "b", "x", "y"]
        relevant = {"a", "b"}
        assert precision_at_k(retrieved, relevant, 2) == 1.0

    def test_k_greater_than_retrieved(self) -> None:
        retrieved = ["a", "x"]
        relevant = {"a", "b"}
        assert precision_at_k(retrieved, relevant, 5) == 0.5

    def test_empty_retrieved(self) -> None:
        assert precision_at_k([], {"a"}, 5) == 0.0

    def test_empty_relevant(self) -> None:
        assert precision_at_k(["a", "b"], set(), 2) == 0.0

    def test_k_zero(self) -> None:
        assert precision_at_k(["a"], {"a"}, 0) == 0.0

    def test_k_negative(self) -> None:
        assert precision_at_k(["a"], {"a"}, -1) == 0.0


class TestRecallAtK:
    def test_all_found(self) -> None:
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert recall_at_k(retrieved, relevant, 3) == 1.0

    def test_none_found(self) -> None:
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, 3) == 0.0

    def test_partial_found(self) -> None:
        retrieved = ["a", "x", "y"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, 3) == 0.5

    def test_k_limits_search(self) -> None:
        retrieved = ["x", "y", "a", "b"]
        relevant = {"a", "b"}
        assert recall_at_k(retrieved, relevant, 2) == 0.0

    def test_empty_relevant(self) -> None:
        assert recall_at_k(["a"], set(), 1) == 0.0

    def test_empty_retrieved(self) -> None:
        assert recall_at_k([], {"a"}, 5) == 0.0

    def test_k_zero(self) -> None:
        assert recall_at_k(["a"], {"a"}, 0) == 0.0


class TestMeanReciprocalRank:
    def test_first_position(self) -> None:
        assert mean_reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0

    def test_second_position(self) -> None:
        assert mean_reciprocal_rank(["x", "a", "c"], {"a"}) == 0.5

    def test_third_position(self) -> None:
        assert mean_reciprocal_rank(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)

    def test_no_relevant(self) -> None:
        assert mean_reciprocal_rank(["x", "y", "z"], {"a"}) == 0.0

    def test_multiple_relevant_returns_first(self) -> None:
        assert mean_reciprocal_rank(["x", "a", "b"], {"a", "b"}) == 0.5

    def test_empty_retrieved(self) -> None:
        assert mean_reciprocal_rank([], {"a"}) == 0.0

    def test_empty_relevant(self) -> None:
        assert mean_reciprocal_rank(["a"], set()) == 0.0


class TestNdcgAtK:
    def test_perfect_ranking(self) -> None:
        retrieved = ["a", "b", "c"]
        relevant = {"a", "b", "c"}
        assert ndcg_at_k(retrieved, relevant, 3) == pytest.approx(1.0)

    def test_worst_ranking(self) -> None:
        retrieved = ["x", "y", "z"]
        relevant = {"a", "b"}
        assert ndcg_at_k(retrieved, relevant, 3) == 0.0

    def test_imperfect_ranking(self) -> None:
        # Relevant item at position 2 instead of 1
        retrieved = ["x", "a"]
        relevant = {"a"}
        # DCG = 1/log2(3) ≈ 0.6309, IDCG = 1/log2(2) = 1.0
        expected = (1.0 / math.log2(3)) / (1.0 / math.log2(2))
        assert ndcg_at_k(retrieved, relevant, 2) == pytest.approx(expected)

    def test_k_zero(self) -> None:
        assert ndcg_at_k(["a"], {"a"}, 0) == 0.0

    def test_empty_relevant(self) -> None:
        assert ndcg_at_k(["a", "b"], set(), 2) == 0.0

    def test_empty_retrieved(self) -> None:
        assert ndcg_at_k([], {"a"}, 2) == 0.0

    def test_single_relevant_at_top(self) -> None:
        retrieved = ["a", "x", "y"]
        relevant = {"a"}
        assert ndcg_at_k(retrieved, relevant, 3) == pytest.approx(1.0)

    def test_k_larger_than_list(self) -> None:
        retrieved = ["a"]
        relevant = {"a", "b"}
        # DCG = 1/log2(2) = 1.0, IDCG = 1/log2(2) + 1/log2(3) ≈ 1.6309
        expected = 1.0 / (1.0 + 1.0 / math.log2(3))
        assert ndcg_at_k(retrieved, relevant, 5) == pytest.approx(expected)
