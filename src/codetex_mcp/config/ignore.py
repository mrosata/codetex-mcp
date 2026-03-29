"""File exclusion filter with chained rules."""

from __future__ import annotations

from pathlib import Path

import pathspec


class IgnoreFilter:
    """Chains default excludes, .gitignore, .codetexignore, size, and binary detection."""

    def __init__(
        self,
        repo_path: Path,
        default_excludes: list[str],
        max_file_size_kb: int,
    ) -> None:
        self._repo_path = repo_path
        self._max_file_size_bytes = max_file_size_kb * 1024

        self._default_spec = pathspec.PathSpec.from_lines(
            "gitignore", default_excludes
        )

        self._gitignore_spec = self._load_spec(repo_path / ".gitignore")
        self._codetexignore_spec = self._load_spec(repo_path / ".codetexignore")

        # Parse negation patterns from .codetexignore separately
        self._codetexignore_negations = self._load_negations(
            repo_path / ".codetexignore"
        )

    @staticmethod
    def _load_spec(path: Path) -> pathspec.PathSpec | None:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        return pathspec.PathSpec.from_lines("gitignore", text.splitlines())

    @staticmethod
    def _load_negations(path: Path) -> pathspec.PathSpec | None:
        """Extract negation patterns (lines starting with !) from an ignore file."""
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        negated = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("!"):
                # Remove the ! prefix to get the actual pattern
                negated.append(stripped[1:])
        if not negated:
            return None
        return pathspec.PathSpec.from_lines("gitignore", negated)

    def is_excluded(self, file_path: Path) -> tuple[bool, str | None]:
        """Check whether a file should be excluded.

        Returns (True, reason) if excluded, (False, None) otherwise.
        ``file_path`` is relative to the repo root.
        """
        rel = str(file_path)

        # 1. Default excludes
        if self._default_spec.match_file(rel):
            return True, "default exclude"

        # 2. .gitignore
        if self._gitignore_spec is not None and self._gitignore_spec.match_file(rel):
            # Check if .codetexignore overrides via negation
            if (
                self._codetexignore_negations is not None
                and self._codetexignore_negations.match_file(rel)
            ):
                pass  # negation overrides — do not exclude
            else:
                return True, "gitignore"

        # 3. .codetexignore (positive patterns)
        if (
            self._codetexignore_spec is not None
            and self._codetexignore_spec.match_file(rel)
        ):
            # A negation in the same file should not re-exclude, but positive patterns do
            # Check if the file also matches a negation — if so, it's not excluded
            if (
                self._codetexignore_negations is not None
                and self._codetexignore_negations.match_file(rel)
            ):
                pass  # negation overrides
            else:
                return True, "codetexignore"

        # 4. File size
        abs_path = self._repo_path / file_path
        if abs_path.is_file():
            try:
                size = abs_path.stat().st_size
                if size > self._max_file_size_bytes:
                    return True, "size threshold"
            except OSError:
                pass

        # 5. Binary detection (null byte in first 8 KB)
        if abs_path.is_file():
            try:
                with open(abs_path, "rb") as f:
                    chunk = f.read(8192)
                if b"\x00" in chunk:
                    return True, "binary"
            except OSError:
                pass

        return False, None

    def filter_files(self, files: list[str]) -> list[str]:
        """Return only non-excluded files."""
        result: list[str] = []
        for f in files:
            excluded, _ = self.is_excluded(Path(f))
            if not excluded:
                result.append(f)
        return result
