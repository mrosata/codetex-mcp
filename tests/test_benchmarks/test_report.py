"""Unit tests for benchmark report generation."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from codetex_mcp.benchmarks.report import get_git_sha, write_report


class TestGetGitSha:
    def test_returns_string(self) -> None:
        sha = get_git_sha()
        assert isinstance(sha, str)
        assert len(sha) > 0

    def test_returns_hex_sha(self) -> None:
        sha = get_git_sha()
        if sha != "unknown":
            assert all(c in "0123456789abcdef" for c in sha)
            assert len(sha) == 40

    def test_returns_unknown_on_failure(self) -> None:
        with patch(
            "codetex_mcp.benchmarks.report.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            assert get_git_sha() == "unknown"


class TestWriteReport:
    def test_creates_file(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "results"
        path = write_report(results_dir, "retrieval", {"precision": 0.8})
        assert path.exists()
        assert path.suffix == ".json"

    def test_creates_directory(self, tmp_path: Path) -> None:
        results_dir = tmp_path / "nested" / "results"
        write_report(results_dir, "retrieval", {"precision": 0.8})
        assert results_dir.is_dir()

    def test_file_content_structure(self, tmp_path: Path) -> None:
        metrics = {"precision_at_5": 0.72, "recall_at_5": 0.65}
        path = write_report(tmp_path, "retrieval", metrics)
        data = json.loads(path.read_text())

        assert "timestamp" in data
        assert "git_sha" in data
        assert data["approach"] == "retrieval"
        assert data["metrics"] == metrics

    def test_includes_per_query(self, tmp_path: Path) -> None:
        per_query = [{"id": "RQ-001", "precision": 0.9}]
        path = write_report(
            tmp_path, "retrieval", {"mean_precision": 0.9}, per_query=per_query
        )
        data = json.loads(path.read_text())
        assert data["per_query"] == per_query

    def test_omits_per_query_when_none(self, tmp_path: Path) -> None:
        path = write_report(tmp_path, "efficiency", {"compression": 5.0})
        data = json.loads(path.read_text())
        assert "per_query" not in data

    def test_filename_includes_approach(self, tmp_path: Path) -> None:
        path = write_report(tmp_path, "efficiency", {"ratio": 1.0})
        assert "efficiency" in path.name

    def test_timestamp_format(self, tmp_path: Path) -> None:
        path = write_report(tmp_path, "retrieval", {"p": 0.5})
        data = json.loads(path.read_text())
        ts = data["timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts

    def test_git_sha_present(self, tmp_path: Path) -> None:
        path = write_report(tmp_path, "retrieval", {"p": 0.5})
        data = json.loads(path.read_text())
        assert isinstance(data["git_sha"], str)
        assert len(data["git_sha"]) > 0
