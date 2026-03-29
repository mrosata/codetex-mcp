"""Fallback regex-based parser for languages without tree-sitter support."""

from __future__ import annotations

import re

import tiktoken

from codetex_mcp.analysis.models import (
    FileAnalysis,
    ImportInfo,
    ParameterInfo,
    SymbolInfo,
)

# Regex patterns for symbol extraction across languages
_SYMBOL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Python: def func_name(params) -> return:
    (
        re.compile(
            r"^[ \t]*def\s+(?P<name>\w+)\s*\((?P<params>[^)]*)\)"
            r"(?:\s*->\s*(?P<return>[^:]+))?\s*:"
        ),
        "function",
    ),
    # Python: class ClassName(bases):
    (
        re.compile(r"^[ \t]*class\s+(?P<name>\w+)\s*(?:\([^)]*\))?\s*:"),
        "class",
    ),
    # JavaScript/TypeScript: function name(params) {
    (
        re.compile(
            r"^[ \t]*(?:export\s+)?(?:async\s+)?function\s+(?P<name>\w+)"
            r"\s*\((?P<params>[^)]*)\)"
        ),
        "function",
    ),
    # JavaScript/TypeScript: class Name { / class Name extends Base {
    (
        re.compile(
            r"^[ \t]*(?:export\s+)?class\s+(?P<name>\w+)"
            r"(?:\s+extends\s+\w+)?"
        ),
        "class",
    ),
    # Go: func name(params) return {
    (
        re.compile(
            r"^func\s+(?:\([^)]+\)\s+)?(?P<name>\w+)"
            r"\s*\((?P<params>[^)]*)\)"
            r"(?:\s+(?P<return>[^{]+))?"
        ),
        "function",
    ),
    # Rust: fn name(params) -> return {
    (
        re.compile(
            r"^[ \t]*(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>\w+)"
            r"\s*\((?P<params>[^)]*)\)"
            r"(?:\s*->\s*(?P<return>[^{]+))?"
        ),
        "function",
    ),
    # Rust: struct/enum/trait
    (
        re.compile(r"^[ \t]*(?:pub\s+)?(?:struct|enum|trait)\s+(?P<name>\w+)"),
        "class",
    ),
    # Java/C++: access return_type name(params) {
    (
        re.compile(
            r"^[ \t]*(?:public|private|protected|static|virtual|override|"
            r"abstract|final|synchronized|native|inline)?"
            r"\s*(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(?P<name>\w+)"
            r"\s*\((?P<params>[^)]*)\)\s*(?:throws\s+\w+(?:,\s*\w+)*)?\s*\{"
        ),
        "function",
    ),
    # Ruby: def method_name(params)
    (
        re.compile(r"^[ \t]*def\s+(?:self\.)?(?P<name>\w+[!?]?)\s*(?:\((?P<params>[^)]*)\))?"),
        "function",
    ),
]

# Import patterns across languages
# Order matters: more specific patterns (with semicolons, quotes, etc.) come first
# to prevent generic patterns from matching incorrectly.
_IMPORT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Java: import package.Class; (must come before Python import to avoid
    # matching "import static" as a Python import of module "static")
    (
        re.compile(r"^[ \t]*import\s+(?:static\s+)?(?P<module>[\w.]+)\s*;"),
        "java_import",
    ),
    # Python: from module import names (must come before generic import)
    (
        re.compile(
            r"^[ \t]*from\s+(?P<module>[\w.]+)\s+import\s+(?P<names>.+)"
        ),
        "python_from",
    ),
    # JavaScript/TypeScript: import { names } from 'module' / import name from 'module'
    (
        re.compile(
            r"""^[ \t]*import\s+(?:\{[^}]+\}|\*\s+as\s+\w+|\w+)"""
            r"""\s+from\s+['"](?P<module>[^'"]+)['"]"""
        ),
        "js_import",
    ),
    # Go: import "path" or import ( ... )
    (re.compile(r'^[ \t]*import\s+"(?P<module>[^"]+)"'), "go_import"),
    # Python: import module (generic, must come after more specific import patterns)
    (re.compile(r"^[ \t]*import\s+(?P<module>[\w.]+)"), "python_import"),
    # JavaScript: require('module')
    (
        re.compile(
            r"""^[ \t]*(?:const|let|var)\s+\w+\s*=\s*require\(\s*['"](?P<module>[^'"]+)['"]\s*\)"""
        ),
        "js_require",
    ),
    # Rust: use path::to::module
    (re.compile(r"^[ \t]*use\s+(?P<module>[\w:]+)"), "rust_use"),
    # C/C++: #include <header> or #include "header"
    (
        re.compile(r'^[ \t]*#\s*include\s+[<"](?P<module>[^>"]+)[>"]'),
        "c_include",
    ),
    # Ruby: require 'module' / require_relative 'module'
    (
        re.compile(
            r"""^[ \t]*require(?:_relative)?\s+['"](?P<module>[^'"]+)['"]"""
        ),
        "ruby_require",
    ),
]

# Comment prefix patterns for extracting file-level docstrings
_LINE_COMMENT_PREFIXES = ("//", "#", "--", ";;")

# Lazy-loaded tiktoken encoder
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _count_tokens(content: str) -> int:
    return len(_get_encoder().encode(content))


def _parse_python_params(params_str: str) -> list[ParameterInfo]:
    """Parse a Python-style parameter string into ParameterInfo list."""
    params: list[ParameterInfo] = []
    if not params_str.strip():
        return params

    for part in params_str.split(","):
        part = part.strip()
        if not part or part == "self" or part == "cls":
            continue

        default_value: str | None = None
        if "=" in part:
            part, default_value = part.rsplit("=", 1)
            part = part.strip()
            default_value = default_value.strip()

        type_annotation: str | None = None
        if ":" in part:
            name, type_annotation = part.split(":", 1)
            name = name.strip()
            type_annotation = type_annotation.strip()
        else:
            name = part.strip()

        # Skip *args, **kwargs prefix but keep the name
        name = name.lstrip("*")
        if name:
            params.append(
                ParameterInfo(
                    name=name,
                    type_annotation=type_annotation or None,
                    default_value=default_value,
                )
            )

    return params


def _extract_docstring(lines: list[str], start_idx: int) -> str | None:
    """Try to extract a docstring following a symbol definition line."""
    # Look at the next non-empty line after the definition
    idx = start_idx + 1
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx >= len(lines):
        return None

    line = lines[idx].strip()

    # Python triple-quoted docstring
    for quote in ('"""', "'''"):
        if line.startswith(quote):
            # Single-line docstring
            if line.count(quote) >= 2 and line.endswith(quote) and len(line) > 6:
                return line[3:-3].strip()
            # Multi-line docstring
            doc_lines = [line[3:]]
            idx += 1
            while idx < len(lines):
                if quote in lines[idx]:
                    doc_lines.append(lines[idx].strip().rstrip(quote))
                    break
                doc_lines.append(lines[idx].strip())
                idx += 1
            return "\n".join(doc_lines).strip()

    return None


def _find_symbol_end(lines: list[str], start_idx: int, language: str | None) -> int:
    """Estimate the end line of a symbol based on indentation or braces."""
    if start_idx >= len(lines):
        return start_idx

    start_line = lines[start_idx]
    start_indent = len(start_line) - len(start_line.lstrip())

    # For brace-delimited languages, count braces
    if language in ("javascript", "typescript", "go", "rust", "java", "cpp", "c", "ruby"):
        brace_count = 0
        found_open = False
        for i in range(start_idx, len(lines)):
            for ch in lines[i]:
                if ch == "{":
                    brace_count += 1
                    found_open = True
                elif ch == "}":
                    brace_count -= 1
            if found_open and brace_count <= 0:
                return i + 1  # 1-based
        return len(lines)

    # For indentation-based languages (Python, Ruby without braces)
    for i in range(start_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= start_indent:
            return i  # 1-based (previous line was the last)
    return len(lines)


class FallbackParser:
    """Regex-based parser for languages without tree-sitter support."""

    def parse(self, content: str, language: str | None) -> FileAnalysis:
        """Parse source content using regex patterns.

        Args:
            content: The source file content.
            language: The detected language, or None if unknown.

        Returns:
            FileAnalysis with extracted symbols, imports, and metrics.
        """
        lines = content.splitlines()
        symbols = self._extract_symbols(lines, language)
        imports = self._extract_imports(lines)
        lines_of_code = len(lines)
        token_count = _count_tokens(content)

        return FileAnalysis(
            path="",  # Caller sets the actual path
            language=language,
            imports=imports,
            symbols=symbols,
            lines_of_code=lines_of_code,
            token_count=token_count,
        )

    def _extract_symbols(
        self, lines: list[str], language: str | None
    ) -> list[SymbolInfo]:
        """Extract symbol definitions from source lines."""
        symbols: list[SymbolInfo] = []
        seen_lines: set[int] = set()

        for line_idx, line in enumerate(lines):
            if line_idx in seen_lines:
                continue

            for pattern, kind in _SYMBOL_PATTERNS:
                match = pattern.match(line)
                if match:
                    name = match.group("name")
                    seen_lines.add(line_idx)

                    # Extract parameters if captured
                    params: list[ParameterInfo] = []
                    try:
                        params_str = match.group("params")
                        if params_str:
                            params = _parse_python_params(params_str)
                    except IndexError:
                        pass

                    # Extract return type if captured
                    return_type: str | None = None
                    try:
                        rt = match.group("return")
                        if rt:
                            return_type = rt.strip()
                    except IndexError:
                        pass

                    # Build the signature from the matched line
                    signature = line.strip().rstrip("{").rstrip(":").strip()

                    # Extract docstring
                    docstring = _extract_docstring(lines, line_idx)

                    # Estimate end line
                    end_line = _find_symbol_end(lines, line_idx, language)

                    symbols.append(
                        SymbolInfo(
                            name=name,
                            kind=kind,  # type: ignore[arg-type]
                            signature=signature,
                            docstring=docstring,
                            start_line=line_idx + 1,  # 1-based
                            end_line=end_line,
                            parameters=params,
                            return_type=return_type,
                            calls=[],
                        )
                    )
                    break  # Only match the first pattern per line

        return symbols

    def _extract_imports(self, lines: list[str]) -> list[ImportInfo]:
        """Extract import statements from source lines."""
        imports: list[ImportInfo] = []

        for line in lines:
            for pattern, kind in _IMPORT_PATTERNS:
                match = pattern.match(line)
                if match:
                    module = match.group("module")
                    names: list[str] = []

                    if kind == "python_from":
                        try:
                            names_str = match.group("names")
                            # Handle parenthesized imports and wildcards
                            names_str = names_str.strip().rstrip("\\").strip("()")
                            if names_str != "*":
                                names = [
                                    n.strip().split(" as ")[0].strip()
                                    for n in names_str.split(",")
                                    if n.strip()
                                ]
                        except IndexError:
                            pass
                    elif kind == "js_import":
                        # Extract names from import { a, b } from 'module'
                        brace_match = re.search(r"\{([^}]+)\}", line)
                        if brace_match:
                            names = [
                                n.strip().split(" as ")[0].strip()
                                for n in brace_match.group(1).split(",")
                                if n.strip()
                            ]

                    imports.append(ImportInfo(module=module, names=names))
                    break  # Only match the first pattern per line

        return imports
