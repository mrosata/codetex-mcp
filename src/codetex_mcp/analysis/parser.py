"""Unified parser dispatcher — tree-sitter with regex fallback."""

from __future__ import annotations

from pathlib import Path

from codetex_mcp.analysis.fallback_parser import FallbackParser
from codetex_mcp.analysis.models import FileAnalysis
from codetex_mcp.analysis.tree_sitter import TreeSitterParser

# File extension to language name mapping
_EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
}


class Parser:
    """Unified parser that delegates to tree-sitter or falls back to regex."""

    def __init__(
        self,
        tree_sitter_parser: TreeSitterParser,
        fallback_parser: FallbackParser,
    ) -> None:
        self._tree_sitter = tree_sitter_parser
        self._fallback = fallback_parser

    def detect_language(self, path: Path) -> str | None:
        """Detect language from file extension.

        Args:
            path: The file path to detect language for.

        Returns:
            Language name string, or None if unrecognized.
        """
        suffix = path.suffix.lower()
        return _EXTENSION_MAP.get(suffix)

    def parse_file(
        self, path: Path, content: str, language: str | None = None
    ) -> FileAnalysis:
        """Parse a source file, using tree-sitter if available.

        Detects language from path if not provided. Tries tree-sitter first,
        falls back to the regex parser if the grammar is unavailable.

        Args:
            path: The file path.
            content: The source file content.
            language: Optional language override. Detected from path if None.

        Returns:
            FileAnalysis with extracted symbols, imports, and metrics.
        """
        if language is None:
            language = self.detect_language(path)

        # Try tree-sitter first if we have a language
        if language is not None and self._tree_sitter.is_language_supported(language):
            result = self._tree_sitter.parse(content, language)
        else:
            result = self._fallback.parse(content, language)

        # Set the actual file path
        result.path = str(path)
        return result
