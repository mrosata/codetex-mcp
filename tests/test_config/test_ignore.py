"""Tests for IgnoreFilter."""

from __future__ import annotations

from pathlib import Path

from codetex_mcp.config.ignore import IgnoreFilter


class TestDefaultExcludes:
    """Default exclude patterns are applied."""

    def test_node_modules_excluded(self, tmp_path: Path) -> None:
        filt = IgnoreFilter(tmp_path, ["node_modules/"], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("node_modules/foo.js"))
        assert excluded is True
        assert reason == "default exclude"

    def test_pycache_excluded(self, tmp_path: Path) -> None:
        filt = IgnoreFilter(tmp_path, ["__pycache__/"], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("src/__pycache__/mod.pyc"))
        assert excluded is True
        assert reason == "default exclude"

    def test_min_js_excluded(self, tmp_path: Path) -> None:
        filt = IgnoreFilter(tmp_path, ["*.min.js"], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("dist/app.min.js"))
        assert excluded is True
        assert reason == "default exclude"

    def test_normal_file_not_excluded(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("print('hi')")
        filt = IgnoreFilter(tmp_path, ["node_modules/", "*.min.js"], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("src/main.py"))
        assert excluded is False
        assert reason is None


class TestGitignore:
    """Gitignore rules are applied."""

    def test_gitignore_excludes_matching_file(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
        (tmp_path / "app.log").write_text("log data")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("app.log"))
        assert excluded is True
        assert reason == "gitignore"

    def test_gitignore_excludes_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build/\n")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("build/output.js"))
        assert excluded is True
        assert reason == "gitignore"

    def test_gitignore_does_not_exclude_non_matching(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "main.py").write_text("code")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("main.py"))
        assert excluded is False
        assert reason is None

    def test_no_gitignore_file(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("code")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("main.py"))
        assert excluded is False
        assert reason is None


class TestCodetexignore:
    """Codetexignore rules are applied."""

    def test_codetexignore_excludes_matching(self, tmp_path: Path) -> None:
        (tmp_path / ".codetexignore").write_text("docs/\n")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("docs/readme.md"))
        assert excluded is True
        assert reason == "codetexignore"

    def test_codetexignore_negation_overrides_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.generated.ts\n")
        (tmp_path / ".codetexignore").write_text("!important.generated.ts\n")
        (tmp_path / "important.generated.ts").write_text("code")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)

        # The negated file should NOT be excluded
        excluded, reason = filt.is_excluded(Path("important.generated.ts"))
        assert excluded is False
        assert reason is None

    def test_codetexignore_negation_does_not_affect_other_matches(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".gitignore").write_text("*.generated.ts\n")
        (tmp_path / ".codetexignore").write_text("!important.generated.ts\n")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)

        # Other .generated.ts files should still be excluded
        excluded, reason = filt.is_excluded(Path("other.generated.ts"))
        assert excluded is True
        assert reason == "gitignore"


class TestSizeThreshold:
    """Files exceeding size threshold are excluded."""

    def test_large_file_excluded(self, tmp_path: Path) -> None:
        big = tmp_path / "large.txt"
        big.write_bytes(b"x" * (600 * 1024))  # 600 KB
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("large.txt"))
        assert excluded is True
        assert reason == "size threshold"

    def test_small_file_not_excluded(self, tmp_path: Path) -> None:
        small = tmp_path / "small.txt"
        small.write_text("hello")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("small.txt"))
        assert excluded is False
        assert reason is None

    def test_exact_threshold_not_excluded(self, tmp_path: Path) -> None:
        exact = tmp_path / "exact.txt"
        exact.write_bytes(b"x" * (512 * 1024))  # exactly 512 KB
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("exact.txt"))
        assert excluded is False
        assert reason is None


class TestBinaryDetection:
    """Binary files (null byte in first 8KB) are excluded."""

    def test_binary_file_excluded(self, tmp_path: Path) -> None:
        binary = tmp_path / "image.dat"
        binary.write_bytes(b"header\x00\x01\x02rest")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("image.dat"))
        assert excluded is True
        assert reason == "binary"

    def test_text_file_not_excluded(self, tmp_path: Path) -> None:
        text = tmp_path / "readme.txt"
        text.write_text("Just text, no null bytes")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("readme.txt"))
        assert excluded is False
        assert reason is None

    def test_null_byte_after_8kb_not_detected(self, tmp_path: Path) -> None:
        beyond = tmp_path / "tricky.bin"
        beyond.write_bytes(b"a" * 8192 + b"\x00")
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("tricky.bin"))
        assert excluded is False
        assert reason is None


class TestFilterFiles:
    """filter_files returns only non-excluded files."""

    def test_filters_multiple_files(self, tmp_path: Path) -> None:
        (tmp_path / "good.py").write_text("code")
        (tmp_path / "bad.log").write_text("log data")
        (tmp_path / ".gitignore").write_text("*.log\n")

        filt = IgnoreFilter(tmp_path, ["*.min.js"], max_file_size_kb=512)
        result = filt.filter_files(["good.py", "bad.log", "lib/app.min.js"])
        assert result == ["good.py"]

    def test_empty_input(self, tmp_path: Path) -> None:
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        assert filt.filter_files([]) == []


class TestFilterChainOrder:
    """Earlier rules in the chain take precedence."""

    def test_default_exclude_checked_before_gitignore(self, tmp_path: Path) -> None:
        # If a file matches both default excludes and gitignore,
        # the reason should be "default exclude" (checked first)
        (tmp_path / ".gitignore").write_text("node_modules/\n")
        filt = IgnoreFilter(tmp_path, ["node_modules/"], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("node_modules/pkg/index.js"))
        assert excluded is True
        assert reason == "default exclude"

    def test_gitignore_checked_before_size(self, tmp_path: Path) -> None:
        # A file matching gitignore should report "gitignore" even if also large
        (tmp_path / ".gitignore").write_text("*.dat\n")
        big = tmp_path / "huge.dat"
        big.write_bytes(b"x" * (600 * 1024))
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("huge.dat"))
        assert excluded is True
        assert reason == "gitignore"

    def test_nonexistent_file_skips_size_and_binary(self, tmp_path: Path) -> None:
        # A file that doesn't exist on disk passes size and binary checks
        filt = IgnoreFilter(tmp_path, [], max_file_size_kb=512)
        excluded, reason = filt.is_excluded(Path("does_not_exist.txt"))
        assert excluded is False
        assert reason is None
