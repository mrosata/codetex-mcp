"""Tests for the unified parser dispatcher."""

from __future__ import annotations

from pathlib import Path

from codetex_mcp.analysis.fallback_parser import FallbackParser
from codetex_mcp.analysis.parser import Parser
from codetex_mcp.analysis.tree_sitter import TreeSitterParser


def _make_parser() -> Parser:
    return Parser(TreeSitterParser(), FallbackParser())


class TestDetectLanguage:
    def test_python(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("main.py")) == "python"

    def test_python_pyw(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("script.pyw")) == "python"

    def test_javascript(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("app.js")) == "javascript"

    def test_javascript_mjs(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("module.mjs")) == "javascript"

    def test_javascript_jsx(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("component.jsx")) == "javascript"

    def test_typescript(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("app.ts")) == "typescript"

    def test_typescript_tsx(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("component.tsx")) == "typescript"

    def test_go(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("main.go")) == "go"

    def test_rust(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("lib.rs")) == "rust"

    def test_java(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("Main.java")) == "java"

    def test_ruby(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("app.rb")) == "ruby"

    def test_cpp(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("main.cpp")) == "cpp"

    def test_cpp_cc(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("main.cc")) == "cpp"

    def test_c_header(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("header.h")) == "cpp"

    def test_unknown_extension(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("data.csv")) is None

    def test_no_extension(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("Makefile")) is None

    def test_case_insensitive(self) -> None:
        parser = _make_parser()
        assert parser.detect_language(Path("Main.PY")) == "python"


class TestParseFile:
    def test_sets_file_path(self) -> None:
        parser = _make_parser()
        result = parser.parse_file(Path("src/main.py"), "x = 1\n")
        assert result.path == "src/main.py"

    def test_detects_language_from_path(self) -> None:
        parser = _make_parser()
        result = parser.parse_file(Path("app.py"), "import os\n")
        assert result.language == "python"

    def test_language_override(self) -> None:
        parser = _make_parser()
        result = parser.parse_file(
            Path("file.txt"), "def foo():\n    pass\n", language="python"
        )
        assert result.language == "python"
        assert len(result.symbols) >= 1

    def test_unknown_language_uses_fallback(self) -> None:
        parser = _make_parser()
        result = parser.parse_file(Path("data.csv"), "a,b,c\n1,2,3\n")
        assert result.language is None
        assert result.lines_of_code == 2

    def test_python_parse_extracts_symbols(self) -> None:
        content = (
            "import os\n\ndef hello(name: str) -> str:\n    return f'Hello, {name}'\n"
        )
        parser = _make_parser()
        result = parser.parse_file(Path("greet.py"), content)
        assert result.language == "python"
        assert len(result.symbols) >= 1
        assert result.symbols[0].name == "hello"
        assert result.path == "greet.py"
        assert result.lines_of_code == 4
        assert result.token_count > 0


# Test tree-sitter vs fallback dispatch
try:
    import tree_sitter_python  # noqa: F401

    _HAS_PYTHON_GRAMMAR = True
except ImportError:
    _HAS_PYTHON_GRAMMAR = False


class TestTreeSitterFallbackDispatch:
    def test_uses_tree_sitter_when_grammar_available(self) -> None:
        """When tree-sitter grammar is available, it should be used."""
        if not _HAS_PYTHON_GRAMMAR:
            # Fall through to fallback test
            parser = _make_parser()
            result = parser.parse_file(Path("test.py"), "def foo():\n    pass\n")
            # Should still produce valid results via fallback
            assert len(result.symbols) >= 1
            return

        parser = _make_parser()
        content = "class MyClass:\n    def method(self) -> None:\n        pass\n"
        result = parser.parse_file(Path("test.py"), content)
        # Tree-sitter distinguishes methods from functions
        method = next(s for s in result.symbols if s.name == "method")
        assert method.kind == "method"

    def test_falls_back_for_unsupported_language(self) -> None:
        """When no tree-sitter grammar, should use fallback parser."""
        parser = _make_parser()
        content = 'func main() {\n    fmt.Println("hello")\n}\n'
        result = parser.parse_file(Path("main.go"), content)
        # Go grammar likely not installed, so fallback is used
        # Either way, should produce valid results
        assert result.language == "go"
        assert result.lines_of_code == 3
        # Fallback should still find the function
        assert len(result.symbols) >= 1
        assert result.symbols[0].name == "main"
