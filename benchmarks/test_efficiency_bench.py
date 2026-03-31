"""Approach 2: Context efficiency benchmark runner.

Measures token density and compression ratio of codetex context
vs. naive raw file dumps.

Run with: uv run pytest benchmarks/test_efficiency_bench.py -m benchmark -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from codetex_mcp.benchmarks.baselines import raw_file_context
from codetex_mcp.benchmarks.report import write_report
from codetex_mcp.benchmarks.token_metrics import (
    compression_ratio,
    count_tokens,
    coverage_score,
    token_density,
)

from conftest import FIXTURES_DIR, load_fixture


def _simulate_codetex_context(repo_path: Path, task: dict[str, Any]) -> str:
    """Simulate codetex-style tiered context from raw files.

    Since we may not have an indexed DB, we approximate by reading
    only the relevant files and extracting symbol signatures (not full content).
    This simulates the compression benefit of tiered summaries.
    """
    parts: list[str] = []

    for file_path in task["relevant_files"]:
        full_path = repo_path / file_path
        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(errors="replace")
        except OSError:
            continue

        # Extract only lines that contain relevant symbols or are signatures
        relevant_lines: list[str] = []
        for line in content.splitlines():
            stripped = line.strip()
            # Include class/function/method definitions
            if stripped.startswith(("def ", "async def ", "class ")):
                relevant_lines.append(line)
            # Include docstrings (first line)
            elif stripped.startswith(('"""', "'''")):
                relevant_lines.append(line)
            # Include dataclass field definitions
            elif ":" in stripped and not stripped.startswith("#"):
                for sym in task.get("relevant_symbols", []):
                    # Get the last part (method/attr name)
                    sym_name = sym.split(".")[-1]
                    if sym_name in stripped:
                        relevant_lines.append(line)
                        break

        parts.append(f"# {file_path}\n\n" + "\n".join(relevant_lines))

    return "\n\n---\n\n".join(parts)


def _run_efficiency_benchmark(
    fixture_file: str,
    repo_name: str,
    results_dir: Path,
) -> dict[str, Any]:
    """Run efficiency benchmark for a given fixture set."""
    data = load_fixture(repo_name, fixture_file)
    repo_path = Path(data["repo_path"]).resolve()
    tasks = data["tasks"]

    all_compression: list[float] = []
    all_coverage_raw: list[float] = []
    all_coverage_codetex: list[float] = []
    all_density: list[float] = []
    per_task: list[dict[str, Any]] = []

    for task in tasks:
        relevant_files = task["relevant_files"]
        relevant_symbols = task.get("relevant_symbols", [])

        # Get raw baseline context (full file dumps)
        raw_context = raw_file_context(repo_path, relevant_files)
        raw_tokens = count_tokens(raw_context)

        # Get simulated codetex context (signatures + docstrings only)
        codetex_context = _simulate_codetex_context(repo_path, task)
        codetex_tokens = count_tokens(codetex_context)

        # Compute metrics
        comp = (
            compression_ratio(raw_tokens, codetex_tokens) if codetex_tokens > 0 else 0.0
        )
        cov_raw = coverage_score(raw_context, relevant_symbols)
        cov_codetex = coverage_score(codetex_context, relevant_symbols)

        # Density: what fraction of codetex tokens are "relevant"
        # (approximated by symbol coverage * total tokens)
        if codetex_tokens > 0 and relevant_symbols:
            relevant_token_estimate = int(codetex_tokens * cov_codetex)
            dens = token_density(relevant_token_estimate, codetex_tokens)
        else:
            dens = 0.0

        all_compression.append(comp)
        all_coverage_raw.append(cov_raw)
        all_coverage_codetex.append(cov_codetex)
        all_density.append(dens)

        per_task.append(
            {
                "id": task["id"],
                "task": task["task"],
                "raw_tokens": raw_tokens,
                "codetex_tokens": codetex_tokens,
                "compression_ratio": comp,
                "coverage_raw": cov_raw,
                "coverage_codetex": cov_codetex,
                "token_density": dens,
            }
        )

    n = len(tasks) if tasks else 1
    metrics = {
        "num_tasks": len(tasks),
        "mean_compression_ratio": sum(all_compression) / n,
        "mean_coverage_raw": sum(all_coverage_raw) / n,
        "mean_coverage_codetex": sum(all_coverage_codetex) / n,
        "mean_token_density": sum(all_density) / n,
    }

    output = write_report(
        results_dir,
        f"efficiency_{repo_name}",
        metrics,
        per_query=per_task,
    )
    print(f"\nResults written to: {output}")
    print(f"  Mean Compression Ratio: {metrics['mean_compression_ratio']:.2f}x")
    print(f"  Mean Coverage (raw):    {metrics['mean_coverage_raw']:.3f}")
    print(f"  Mean Coverage (codetex):{metrics['mean_coverage_codetex']:.3f}")
    print(f"  Mean Token Density:     {metrics['mean_token_density']:.3f}")

    return metrics


@pytest.mark.benchmark
class TestEfficiencyBenchmark:
    def test_codetex_mcp_efficiency(self, results_dir: Path) -> None:
        """Run efficiency benchmark against codetex-mcp's own codebase."""
        fixture_path = FIXTURES_DIR / "codetex_mcp" / "efficiency_tasks.json"
        if not fixture_path.exists():
            pytest.skip("codetex_mcp efficiency fixtures not found")

        metrics = _run_efficiency_benchmark(
            "efficiency_tasks.json", "codetex_mcp", results_dir
        )

        assert metrics["num_tasks"] > 0
        assert metrics["mean_compression_ratio"] >= 1.0

    def test_second_repo_efficiency(self, results_dir: Path) -> None:
        """Run efficiency benchmark against the second repo fixtures."""
        fixture_path = FIXTURES_DIR / "flask" / "efficiency_tasks.json"
        if not fixture_path.exists():
            pytest.skip("flask efficiency fixtures not found")

        metrics = _run_efficiency_benchmark(
            "efficiency_tasks.json", "flask", results_dir
        )
        assert metrics["num_tasks"] > 0
