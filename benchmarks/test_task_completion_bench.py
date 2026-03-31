"""Approach 3: Task completion evaluation benchmark runner.

Evaluates coding task correctness by comparing LLM outputs against
verifiable ground truth answers. Supports running with and without
codetex context to measure context impact.

Run with: uv run pytest benchmarks/test_task_completion_bench.py -m benchmark -v

NOTE: This runner uses simulated LLM responses (the verifiable_answer field)
to validate the scoring framework itself. Real LLM A/B testing requires
API calls and is deferred to US-034/US-035.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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

    # Add task description as context framing
    parts.append(f"Task: {task['task']}")
    parts.append("")

    # Add relevant file contents (simulating Tier 2 file summaries)
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


def _run_task_completion_benchmark(
    fixture_file: str,
    repo_name: str,
    results_dir: Path,
    with_context: bool = False,
) -> dict[str, Any]:
    """Run task completion benchmark for a given fixture set.

    When with_context=False, scores the verifiable_answer directly
    (baseline: perfect answer without needing context).
    When with_context=True, also generates context to validate
    the framework's ability to produce context.

    In real usage, this would send tasks to an LLM with/without
    codetex context and score the LLM's response.
    """
    data = load_fixture(repo_name, fixture_file)
    repo_path = Path(data["repo_path"]).resolve()
    tasks = data["tasks"]

    all_correctness: list[float] = []
    per_task: list[dict[str, Any]] = []

    for task in tasks:
        # Use the verifiable answer as the "LLM response"
        # In real A/B testing, this would be the actual LLM output
        actual = task.get("verifiable_answer", "")

        # Score the response
        scores = _score_task(task, actual)
        all_correctness.append(scores["correctness"])

        task_result: dict[str, Any] = {
            "id": task["id"],
            "task": task["task"],
            **scores,
        }

        # If running with context, also generate and record context
        if with_context:
            context = _build_codetex_context(repo_path, task)
            task_result["context_tokens"] = len(context.split())

        per_task.append(task_result)

    n = len(tasks) if tasks else 1
    approach_suffix = "with_context" if with_context else "baseline"

    metrics: dict[str, Any] = {
        "approach": f"task_completion_{approach_suffix}",
        "num_tasks": len(tasks),
        "mean_correctness": sum(all_correctness) / n,
        "mean_symbol_presence": (
            sum(t["symbol_presence"] for t in per_task) / n
        ),
        "mean_keyword_overlap": (
            sum(t["keyword_overlap"] for t in per_task) / n
        ),
        "mean_line_coverage": (
            sum(t["line_coverage"] for t in per_task) / n
        ),
        "success_rate": success_rate(all_correctness),
    }

    output = write_report(
        results_dir,
        f"task_completion_{repo_name}_{approach_suffix}",
        metrics,
        per_query=per_task,
    )
    print(f"\nResults written to: {output}")
    print(f"  Approach:              {approach_suffix}")
    print(f"  Mean Correctness:      {metrics['mean_correctness']:.3f}")
    print(f"  Mean Symbol Presence:  {metrics['mean_symbol_presence']:.3f}")
    print(f"  Mean Keyword Overlap:  {metrics['mean_keyword_overlap']:.3f}")
    print(f"  Mean Line Coverage:    {metrics['mean_line_coverage']:.3f}")
    print(f"  Success Rate:          {metrics['success_rate']:.3f}")

    return metrics


@pytest.mark.benchmark
class TestTaskCompletionBenchmark:
    def test_codetex_mcp_baseline(self, results_dir: Path) -> None:
        """Run task completion benchmark without codetex context (baseline)."""
        fixture_path = (
            FIXTURES_DIR / "codetex_mcp" / "task_completion_tasks.json"
        )
        if not fixture_path.exists():
            pytest.skip("codetex_mcp task completion fixtures not found")

        metrics = _run_task_completion_benchmark(
            "task_completion_tasks.json",
            "codetex_mcp",
            results_dir,
            with_context=False,
        )

        assert metrics["num_tasks"] > 0
        assert 0.0 <= metrics["mean_correctness"] <= 1.0
        assert 0.0 <= metrics["success_rate"] <= 1.0

    def test_codetex_mcp_with_context(self, results_dir: Path) -> None:
        """Run task completion benchmark with codetex context."""
        fixture_path = (
            FIXTURES_DIR / "codetex_mcp" / "task_completion_tasks.json"
        )
        if not fixture_path.exists():
            pytest.skip("codetex_mcp task completion fixtures not found")

        metrics = _run_task_completion_benchmark(
            "task_completion_tasks.json",
            "codetex_mcp",
            results_dir,
            with_context=True,
        )

        assert metrics["num_tasks"] > 0
        assert 0.0 <= metrics["mean_correctness"] <= 1.0
        assert 0.0 <= metrics["success_rate"] <= 1.0
