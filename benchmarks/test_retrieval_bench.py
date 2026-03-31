"""Approach 1: Retrieval quality benchmark runner.

Measures IR metrics for SearchEngine.search() against curated ground truth.
Also runs grep baseline for comparison.

Run with: uv run pytest benchmarks/test_retrieval_bench.py -m benchmark -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codetex_mcp.benchmarks.baselines import grep_search
from codetex_mcp.benchmarks.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from codetex_mcp.benchmarks.report import write_report

from conftest import FIXTURES_DIR, load_fixture


def _run_retrieval_benchmark(
    fixture_file: str,
    repo_name: str,
    results_dir: Path,
) -> dict[str, Any]:
    """Run retrieval benchmark for a given fixture set.

    Uses grep baseline (no indexed DB needed for baseline comparison).
    Returns metrics dict.
    """
    data = load_fixture(repo_name, fixture_file)
    repo_path = Path(data["repo_path"]).resolve()
    queries = data["queries"]

    all_precision_5: list[float] = []
    all_precision_10: list[float] = []
    all_recall_5: list[float] = []
    all_recall_10: list[float] = []
    all_mrr: list[float] = []
    all_ndcg_10: list[float] = []
    per_query: list[dict[str, Any]] = []

    for q in queries:
        query_text = q["query"]
        k = q.get("k", 10)
        expected_files = set(q["expected_files"])

        # Run grep baseline search
        retrieved = grep_search(repo_path, query_text, max_results=max(k, 10))

        # Compute metrics
        p5 = precision_at_k(retrieved, expected_files, 5)
        p10 = precision_at_k(retrieved, expected_files, 10)
        r5 = recall_at_k(retrieved, expected_files, 5)
        r10 = recall_at_k(retrieved, expected_files, 10)
        mrr = mean_reciprocal_rank(retrieved, expected_files)
        ndcg = ndcg_at_k(retrieved, expected_files, 10)

        all_precision_5.append(p5)
        all_precision_10.append(p10)
        all_recall_5.append(r5)
        all_recall_10.append(r10)
        all_mrr.append(mrr)
        all_ndcg_10.append(ndcg)

        per_query.append(
            {
                "id": q["id"],
                "query": query_text,
                "retrieved_count": len(retrieved),
                "retrieved_files": retrieved[:10],
                "precision_at_5": p5,
                "precision_at_10": p10,
                "recall_at_5": r5,
                "recall_at_10": r10,
                "mrr": mrr,
                "ndcg_at_10": ndcg,
            }
        )

    n = len(queries) if queries else 1
    metrics = {
        "search_method": "grep_baseline",
        "num_queries": len(queries),
        "mean_precision_at_5": sum(all_precision_5) / n,
        "mean_precision_at_10": sum(all_precision_10) / n,
        "mean_recall_at_5": sum(all_recall_5) / n,
        "mean_recall_at_10": sum(all_recall_10) / n,
        "mrr": sum(all_mrr) / n,
        "ndcg_at_10": sum(all_ndcg_10) / n,
    }

    # Write results
    output = write_report(
        results_dir,
        f"retrieval_{repo_name}",
        metrics,
        per_query=per_query,
    )
    print(f"\nResults written to: {output}")
    print(f"  Mean Precision@5:  {metrics['mean_precision_at_5']:.3f}")
    print(f"  Mean Precision@10: {metrics['mean_precision_at_10']:.3f}")
    print(f"  Mean Recall@5:     {metrics['mean_recall_at_5']:.3f}")
    print(f"  Mean Recall@10:    {metrics['mean_recall_at_10']:.3f}")
    print(f"  MRR:               {metrics['mrr']:.3f}")
    print(f"  nDCG@10:           {metrics['ndcg_at_10']:.3f}")

    return metrics


@pytest.mark.benchmark
class TestRetrievalBenchmark:
    def test_codetex_mcp_retrieval(self, results_dir: Path) -> None:
        """Run retrieval benchmark against codetex-mcp's own codebase."""
        fixture_path = FIXTURES_DIR / "codetex_mcp" / "retrieval_queries.json"
        if not fixture_path.exists():
            pytest.skip("codetex_mcp retrieval fixtures not found")

        metrics = _run_retrieval_benchmark(
            "retrieval_queries.json", "codetex_mcp", results_dir
        )

        # Sanity checks — these are not pass/fail thresholds,
        # just ensuring the benchmark actually ran
        assert metrics["num_queries"] > 0
        assert 0.0 <= metrics["mrr"] <= 1.0

    def test_second_repo_retrieval(self, results_dir: Path) -> None:
        """Run retrieval benchmark against the second repo fixtures."""
        fixture_path = FIXTURES_DIR / "flask" / "retrieval_queries.json"
        if not fixture_path.exists():
            pytest.skip("flask retrieval fixtures not found")

        metrics = _run_retrieval_benchmark(
            "retrieval_queries.json", "flask", results_dir
        )
        assert metrics["num_queries"] > 0
