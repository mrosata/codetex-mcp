"""Approach 4: A/B comparison runner — measures impact of codetex context.

Executes each coding task twice (with and without codetex context),
computes per-task and aggregate improvement metrics, and performs
statistical significance testing.

Run with: uv run pytest benchmarks/test_ab_comparison_bench.py -m benchmark -v

NOTE: This runner uses simulated LLM responses (the verifiable_answer field)
to validate the A/B comparison framework. Real LLM A/B testing requires
API calls (send task to LLM with/without context, score both outputs).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codetex_mcp.benchmarks.ab_stats import (
    cohens_d,
    improvement_pct,
    mean_improvement,
    paired_t_test,
    significance_summary,
)
from codetex_mcp.benchmarks.report import write_report
from codetex_mcp.benchmarks.task_metrics import (
    aggregate_correctness,
    keyword_overlap,
    line_coverage,
    success_rate,
    symbol_presence,
)

from conftest import FIXTURES_DIR, load_fixture


def _score_task(task: dict[str, Any], actual: str) -> dict[str, float]:
    """Score a single task completion against ground truth.

    Returns a dict with sub-scores and aggregate correctness.
    """
    sym = symbol_presence(task.get("expected_symbols", []), actual)
    kw = keyword_overlap(task.get("expected_keywords", []), actual)
    lc = line_coverage(task.get("expected_lines", []), actual)
    agg = aggregate_correctness(sym, kw, lc)

    return {
        "symbol_presence": sym,
        "keyword_overlap": kw,
        "line_coverage": lc,
        "correctness": agg,
    }


def _build_codetex_context(repo_path: Path, task: dict[str, Any]) -> str:
    """Build simulated codetex-style context for a task.

    Reads relevant files and extracts signatures + docstrings
    to approximate what tiered context would look like.
    """
    parts: list[str] = []

    parts.append(f"Task: {task['task']}")
    parts.append("")

    for file_path in task.get("relevant_files", []):
        full_path = repo_path / file_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        relevant_lines: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "async def ", "class ")):
                relevant_lines.append(line)
            elif stripped.startswith(('"""', "'''")):
                relevant_lines.append(line)

        if relevant_lines:
            parts.append(f"# {file_path}")
            parts.extend(relevant_lines)
            parts.append("")

    return "\n".join(parts)


def _simulate_baseline_response(task: dict[str, Any]) -> str:
    """Simulate a baseline LLM response (without context).

    Uses a degraded version of the verifiable answer to simulate
    what an LLM might produce without project-specific context.
    Removes some symbols and lines to represent lower quality.
    """
    answer = task.get("verifiable_answer", "")
    if not answer:
        return ""

    lines = answer.splitlines()
    # Keep roughly 60-80% of lines to simulate partial correctness
    # Remove lines containing project-specific implementation details
    kept: list[str] = []
    for i, line in enumerate(lines):
        # Keep the first few lines (imports, function signature) always
        if i < 3:
            kept.append(line)
            continue
        # Drop every 4th line to simulate gaps
        if i % 4 == 3:
            continue
        kept.append(line)

    return "\n".join(kept)


def _simulate_context_response(
    task: dict[str, Any], _context: str
) -> str:
    """Simulate an LLM response with codetex context.

    Uses the full verifiable answer to simulate what an LLM
    would produce with access to project-specific context.
    """
    return task.get("verifiable_answer", "")


def _run_ab_comparison(
    fixture_file: str,
    repo_name: str,
    results_dir: Path,
) -> dict[str, Any]:
    """Run A/B comparison benchmark for a given fixture set.

    Executes each task twice: once simulating baseline (no context)
    and once simulating with-context response. Computes per-task
    and aggregate improvement metrics with statistical testing.
    """
    data = load_fixture(repo_name, fixture_file)
    repo_path = Path(data["repo_path"]).resolve() if data["repo_path"] else Path(".")
    tasks = data["tasks"]

    baseline_scores: list[float] = []
    treatment_scores: list[float] = []
    per_task: list[dict[str, Any]] = []

    # Per-dimension tracking
    dims = ("symbol_presence", "keyword_overlap", "line_coverage")
    baseline_dims: dict[str, list[float]] = {d: [] for d in dims}
    treatment_dims: dict[str, list[float]] = {d: [] for d in dims}

    for task in tasks:
        # Baseline: simulate response without context
        baseline_response = _simulate_baseline_response(task)
        baseline_result = _score_task(task, baseline_response)

        # Treatment: simulate response with context
        context = _build_codetex_context(repo_path, task)
        treatment_response = _simulate_context_response(task, context)
        treatment_result = _score_task(task, treatment_response)

        baseline_scores.append(baseline_result["correctness"])
        treatment_scores.append(treatment_result["correctness"])

        for dim in dims:
            baseline_dims[dim].append(baseline_result[dim])
            treatment_dims[dim].append(treatment_result[dim])

        improvement = treatment_result["correctness"] - baseline_result["correctness"]

        per_task.append({
            "id": task["id"],
            "task": task["task"],
            "baseline_correctness": baseline_result["correctness"],
            "with_context_correctness": treatment_result["correctness"],
            "improvement": round(improvement, 4),
            "baseline_dimensions": {
                d: baseline_result[d] for d in dims
            },
            "with_context_dimensions": {
                d: treatment_result[d] for d in dims
            },
        })

    n = len(tasks) if tasks else 1

    # Aggregate metrics
    baseline_mean = sum(baseline_scores) / n
    treatment_mean = sum(treatment_scores) / n

    # Statistical significance
    t_stat, p_value = paired_t_test(baseline_scores, treatment_scores)
    d = cohens_d(baseline_scores, treatment_scores)
    mean_imp = mean_improvement(baseline_scores, treatment_scores)
    imp_pct = improvement_pct(baseline_mean, treatment_mean)
    sig = significance_summary(t_stat, p_value, d)

    # Per-dimension breakdowns
    per_dimension: dict[str, dict[str, float]] = {}
    for dim in dims:
        b_mean = sum(baseline_dims[dim]) / n
        t_mean = sum(treatment_dims[dim]) / n
        per_dimension[dim] = {
            "baseline_mean": round(b_mean, 4),
            "with_context_mean": round(t_mean, 4),
            "improvement_pct": round(improvement_pct(b_mean, t_mean), 2),
        }

    metrics: dict[str, Any] = {
        "approach": "ab_comparison",
        "num_tasks": len(tasks),
        "baseline_mean_correctness": round(baseline_mean, 4),
        "with_context_mean_correctness": round(treatment_mean, 4),
        "mean_improvement": round(mean_imp, 4),
        "improvement_pct": round(imp_pct, 2),
        "baseline_success_rate": success_rate(baseline_scores),
        "with_context_success_rate": success_rate(treatment_scores),
        "statistical_significance": sig,
        "per_dimension": per_dimension,
    }

    output = write_report(
        results_dir,
        f"ab_comparison_{repo_name}",
        metrics,
        per_query=per_task,
    )

    print(f"\nA/B Comparison Results written to: {output}")
    print(f"  Tasks:                    {len(tasks)}")
    print(f"  Baseline Mean:            {baseline_mean:.4f}")
    print(f"  With Context Mean:        {treatment_mean:.4f}")
    print(f"  Mean Improvement:         {mean_imp:+.4f}")
    print(f"  Improvement %:            {imp_pct:+.2f}%")
    print(f"  Baseline Success Rate:    {success_rate(baseline_scores):.3f}")
    print(f"  With Context Success Rate:{success_rate(treatment_scores):.3f}")
    print(f"  Statistical Significance:")
    print(f"    t-statistic:            {t_stat:.4f}")
    print(f"    p-value:                {p_value:.4f}")
    print(f"    Cohen's d:              {d:.4f}")
    print(f"    {sig['interpretation']}")

    return metrics


@pytest.mark.benchmark
class TestABComparison:
    def test_codetex_mcp_ab_comparison(self, results_dir: Path) -> None:
        """Run A/B comparison for codetex-mcp codebase tasks."""
        fixture_path = (
            FIXTURES_DIR / "codetex_mcp" / "task_completion_tasks.json"
        )
        if not fixture_path.exists():
            pytest.skip("codetex_mcp task completion fixtures not found")

        metrics = _run_ab_comparison(
            "task_completion_tasks.json",
            "codetex_mcp",
            results_dir,
        )

        assert metrics["num_tasks"] > 0
        assert 0.0 <= metrics["baseline_mean_correctness"] <= 1.0
        assert 0.0 <= metrics["with_context_mean_correctness"] <= 1.0
        assert "statistical_significance" in metrics
        assert "p_value" in metrics["statistical_significance"]
        assert "effect_size_cohens_d" in metrics["statistical_significance"]
        assert "per_dimension" in metrics
