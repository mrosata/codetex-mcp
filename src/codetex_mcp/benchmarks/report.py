"""Benchmark result writer — produces structured JSON reports."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_git_sha() -> str:
    """Get current git HEAD SHA, or 'unknown' if not in a repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def write_report(
    results_dir: Path,
    approach: str,
    metrics: dict[str, float],
    per_query: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a benchmark result JSON file.

    Args:
        results_dir: Directory to write the result file to.
        approach: Name of the approach (e.g., "retrieval", "efficiency").
        metrics: Aggregated metric values.
        per_query: Optional per-query/per-task breakdown.

    Returns:
        Path to the written JSON file.
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    filename = now.strftime("%Y%m%d_%H%M%S") + f"_{approach}.json"

    report: dict[str, Any] = {
        "timestamp": timestamp,
        "git_sha": get_git_sha(),
        "approach": approach,
        "metrics": metrics,
    }
    if per_query is not None:
        report["per_query"] = per_query

    results_dir.mkdir(parents=True, exist_ok=True)
    output_path = results_dir / filename
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    return output_path
