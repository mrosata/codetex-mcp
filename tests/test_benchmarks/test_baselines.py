"""Unit tests for baseline implementations."""

from __future__ import annotations

from pathlib import Path

import pytest

from codetex_mcp.benchmarks.baselines import grep_context, grep_search, raw_file_context


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    """Create a minimal repo-like directory with Python files."""
    src = tmp_path / "src"
    src.mkdir()

    (src / "search.py").write_text(
        "def search(query):\n    # semantic search over embeddings\n    pass\n"
    )
    (src / "utils.py").write_text("def helper():\n    # utility function\n    pass\n")
    (src / "embeddings.py").write_text(
        "def embed(text):\n    # generate embeddings for search\n    pass\n"
    )
    return tmp_path


class TestGrepSearch:
    def test_finds_matching_files(self, sample_repo: Path) -> None:
        results = grep_search(sample_repo, "search")
        assert len(results) > 0
        assert any("search.py" in r for r in results)

    def test_returns_relative_paths(self, sample_repo: Path) -> None:
        results = grep_search(sample_repo, "search")
        for r in results:
            assert not r.startswith("/")

    def test_respects_max_results(self, sample_repo: Path) -> None:
        results = grep_search(sample_repo, "def", max_results=1)
        assert len(results) <= 1

    def test_empty_query(self, sample_repo: Path) -> None:
        results = grep_search(sample_repo, "")
        assert results == []

    def test_no_matches(self, sample_repo: Path) -> None:
        results = grep_search(sample_repo, "nonexistentterm12345")
        assert results == []

    def test_multi_keyword_ranks_by_hits(self, sample_repo: Path) -> None:
        # "search" and "embeddings" both appear in embeddings.py
        results = grep_search(sample_repo, "search embeddings")
        assert len(results) > 0


class TestRawFileContext:
    def test_concatenates_files(self, sample_repo: Path) -> None:
        context = raw_file_context(sample_repo, ["src/search.py", "src/utils.py"])
        assert "src/search.py" in context
        assert "src/utils.py" in context
        assert "def search" in context
        assert "def helper" in context

    def test_missing_file_skipped(self, sample_repo: Path) -> None:
        context = raw_file_context(sample_repo, ["src/search.py", "src/nonexistent.py"])
        assert "def search" in context
        assert "nonexistent" not in context

    def test_empty_list(self, sample_repo: Path) -> None:
        context = raw_file_context(sample_repo, [])
        assert context == ""

    def test_includes_file_headers(self, sample_repo: Path) -> None:
        context = raw_file_context(sample_repo, ["src/search.py"])
        assert "# src/search.py" in context


class TestGrepContext:
    def test_returns_matching_context(self, sample_repo: Path) -> None:
        context = grep_context(sample_repo, "search")
        assert "search" in context.lower()

    def test_empty_query(self, sample_repo: Path) -> None:
        assert grep_context(sample_repo, "") == ""

    def test_no_matches(self, sample_repo: Path) -> None:
        context = grep_context(sample_repo, "nonexistentterm12345")
        assert context == ""

    def test_includes_keyword_header(self, sample_repo: Path) -> None:
        context = grep_context(sample_repo, "search")
        assert "# grep: search" in context
