"""Shared fixtures for benchmark runners."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BENCHMARKS_DIR = Path(__file__).parent
FIXTURES_DIR = BENCHMARKS_DIR / "fixtures"
RESULTS_DIR = BENCHMARKS_DIR / "results"


def load_fixture(repo_name: str, fixture_file: str) -> dict[str, Any]:
    """Load a JSON fixture file for a given repo."""
    path = FIXTURES_DIR / repo_name / fixture_file
    return json.loads(path.read_text())  # type: ignore[no-any-return]


@pytest.fixture
def results_dir() -> Path:
    """Return the benchmark results directory, creating it if needed."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return RESULTS_DIR
