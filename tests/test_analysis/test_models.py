"""Tests for analysis data models."""

from __future__ import annotations

from codetex_mcp.analysis.models import (
    FileAnalysis,
    ImportInfo,
    ParameterInfo,
    SymbolInfo,
)


class TestParameterInfo:
    def test_defaults(self) -> None:
        p = ParameterInfo(name="x")
        assert p.name == "x"
        assert p.type_annotation is None
        assert p.default_value is None

    def test_with_type_and_default(self) -> None:
        p = ParameterInfo(name="x", type_annotation="int", default_value="0")
        assert p.type_annotation == "int"
        assert p.default_value == "0"


class TestSymbolInfo:
    def test_function_symbol(self) -> None:
        s = SymbolInfo(
            name="foo",
            kind="function",
            signature="def foo(x: int) -> str",
            start_line=1,
            end_line=5,
        )
        assert s.name == "foo"
        assert s.kind == "function"
        assert s.docstring is None
        assert s.parameters == []
        assert s.return_type is None
        assert s.calls == []

    def test_class_symbol(self) -> None:
        s = SymbolInfo(
            name="MyClass",
            kind="class",
            signature="class MyClass(Base)",
        )
        assert s.kind == "class"

    def test_all_kinds(self) -> None:
        for kind in ("function", "method", "class", "variable", "constant"):
            s = SymbolInfo(name="x", kind=kind, signature="x")  # type: ignore[arg-type]
            assert s.kind == kind


class TestImportInfo:
    def test_simple_import(self) -> None:
        i = ImportInfo(module="os")
        assert i.module == "os"
        assert i.names == []

    def test_import_with_names(self) -> None:
        i = ImportInfo(module="os.path", names=["join", "exists"])
        assert i.names == ["join", "exists"]


class TestFileAnalysis:
    def test_defaults(self) -> None:
        fa = FileAnalysis(path="test.py", language="python")
        assert fa.path == "test.py"
        assert fa.language == "python"
        assert fa.imports == []
        assert fa.symbols == []
        assert fa.lines_of_code == 0
        assert fa.token_count == 0

    def test_with_data(self) -> None:
        fa = FileAnalysis(
            path="test.py",
            language="python",
            imports=[ImportInfo(module="os")],
            symbols=[SymbolInfo(name="main", kind="function", signature="def main()")],
            lines_of_code=10,
            token_count=50,
        )
        assert len(fa.imports) == 1
        assert len(fa.symbols) == 1
        assert fa.lines_of_code == 10
        assert fa.token_count == 50

    def test_none_language(self) -> None:
        fa = FileAnalysis(path="unknown.xyz", language=None)
        assert fa.language is None
